import discord
from discord import app_commands
from discord.ext import commands, tasks
import logging
import random
import time

from ..services import database as db
from ..services.permissions import permission_manager
from ..utils.helpers import parse_duration

logger = logging.getLogger("OmniBot.community")

POLL_EMOJIS = ["1\u20e3", "2\u20e3", "3\u20e3", "4\u20e3", "5\u20e3", "6\u20e3", "7\u20e3", "8\u20e3", "9\u20e3", "\U0001f51f"]
GIVEAWAY_EMOJI = "\U0001f389"


class CommunityCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    async def cog_load(self):
        self.check_giveaways.start()
        self.check_reminders.start()

    async def cog_unload(self):
        self.check_giveaways.cancel()
        self.check_reminders.cancel()

    @app_commands.command(name="poll", description="Crear una encuesta con opciones")
    @app_commands.describe(pregunta="La pregunta", opciones="Opciones separadas por comas (max 10)")
    async def poll_cmd(self, interaction: discord.Interaction, pregunta: str, *, opciones: str):
        options = [o.strip() for o in opciones.split(",") if o.strip()][:10]
        if len(options) < 2:
            await interaction.response.send_message("Necesitas al menos 2 opciones separadas por comas.")
            return

        lines = [f"**{i+1}.** {opt}" for i, opt in enumerate(options)]

        embed = discord.Embed(
            title=f"{pregunta}",
            description="\n".join(lines),
            color=0x5865F2
        )
        embed.set_footer(text=f"Encuesta de {interaction.user.display_name} | Reacciona para votar")
        await interaction.response.send_message(embed=embed)
        msg = await interaction.original_response()

        for i in range(len(options)):
            try:
                await msg.add_reaction(POLL_EMOJIS[i])
            except Exception:
                pass

    @app_commands.command(name="giveaway", description="Iniciar un sorteo (MOD+)")
    @app_commands.describe(premio="Que se sortea", duracion="Ej: 1h, 30m, 2d", ganadores="Cuantos ganan (default 1)")
    async def giveaway_cmd(self, interaction: discord.Interaction, premio: str, duracion: str, ganadores: int = 1):
        if not permission_manager.has_permission(interaction.user, "warn_user"):
            await interaction.response.send_message("Solo **MODERADOR** o superior puede usar este comando.")
            return

        seconds = parse_duration(duracion)
        if seconds < 30 or seconds > 604800:
            await interaction.response.send_message("Duracion invalida. Debe ser entre 30 segundos y 7 dias. Ej: 1h, 30m, 2d")
            return

        if ganadores < 1 or ganadores > 20:
            await interaction.response.send_message("Numero de ganadores invalido (1-20).")
            return

        ends_at = time.time() + seconds
        ends_str = f"<t:{int(ends_at)}:R>"

        gid = await db.create_giveaway(interaction.guild.id, interaction.channel.id, premio, ganadores, ends_at, interaction.user.id)

        embed = discord.Embed(
            title=f"{GIVEAWAY_EMOJI} SORTEO {GIVEAWAY_EMOJI}",
            description=(
                f"**{premio}**\n\n"
                f"Reacciona con {GIVEAWAY_EMOJI} para participar\n\n"
                f"Ganadores: **{ganadores}**\n"
                f"Termina: {ends_str}\n"
                f"Organiza: {interaction.user.mention}"
            ),
            color=0x57F287
        )
        embed.set_footer(text=f"ID: {gid}")
        await interaction.response.send_message(embed=embed)
        msg = await interaction.original_response()
        try:
            await msg.add_reaction(GIVEAWAY_EMOJI)
        except Exception as e:
            logger.error(f"No se pudo añadir la reacción al sorteo {gid}: {e}")
        await db.update_giveaway_message(gid, msg.id)

    @app_commands.command(name="remind", description="Programar un recordatorio")
    @app_commands.describe(tiempo="Ej: 10m, 2h, 1d", mensaje="Que quieres recordar")
    async def remind_cmd(self, interaction: discord.Interaction, tiempo: str, *, mensaje: str):
        seconds = parse_duration(tiempo)
        if seconds < 30 or seconds > 2592000:
            await interaction.response.send_message("Tiempo invalido. Debe ser entre 30 segundos y 30 dias. Ej: 10m, 2h, 1d")
            return

        remind_at = time.time() + seconds
        await db.create_reminder(interaction.user.id, interaction.channel.id, mensaje, remind_at)

        ts = f"<t:{int(remind_at)}:R>"
        await interaction.response.send_message(f"Te avisare {ts}: {mensaje}", ephemeral=True)

    @tasks.loop(seconds=30)
    async def check_giveaways(self):
        try:
            await self._check_giveaways()
        except Exception as e:
            logger.error(f"Giveaway loop error: {e}", exc_info=True)
            await self.bot.report_task_error("check_giveaways", e)

    async def _check_giveaways(self):
        gaws = await db.get_active_giveaways()
        for gw in gaws:
            guild = self.bot.get_guild(gw["guild_id"])
            if not guild:
                continue
            channel = guild.get_channel(gw["channel_id"])
            if not channel:
                continue

            await db.end_giveaway(gw["id"])

            try:
                msg = await channel.fetch_message(gw["message_id"])
            except Exception:
                continue

            reaction = None
            for r in msg.reactions:
                if str(r.emoji) == GIVEAWAY_EMOJI:
                    reaction = r
                    break

            if not reaction:
                try:
                    await channel.send(f"{GIVEAWAY_EMOJI} **Sorteo terminado:** {gw['prize']}\nNo hubo participantes.")
                except discord.Forbidden:
                    pass
                continue

            users = [u async for u in reaction.users() if not u.bot]
            if not users:
                try:
                    await channel.send(f"{GIVEAWAY_EMOJI} **Sorteo terminado:** {gw['prize']}\nNo hubo participantes.")
                except discord.Forbidden:
                    pass
                continue

            w_count = min(gw["winners"], len(users))
            winners = random.sample(users, w_count)
            winner_mentions = ", ".join(w.mention for w in winners)

            try:
                await channel.send(
                    f"{GIVEAWAY_EMOJI} **SORTEO FINALIZADO** {GIVEAWAY_EMOJI}\n\n"
                    f"Premio: **{gw['prize']}**\n"
                    f"Ganador(es): {winner_mentions}\n"
                    f"Participantes: {len(users)}\n\n"
                    f"Organizado por <@{gw['created_by']}>"
                )
            except discord.Forbidden:
                logger.warning(f"Giveaway {gw['id']} ended but could not announce in #{channel}")

    @tasks.loop(seconds=30)
    async def check_reminders(self):
        try:
            await self._check_reminders()
        except Exception as e:
            logger.error(f"Reminder loop error: {e}", exc_info=True)
            await self.bot.report_task_error("check_reminders", e)

    async def _check_reminders(self):
        reminders = await db.get_due_reminders()
        for r in reminders:
            try:
                channel = self.bot.get_channel(r["channel_id"])
                if channel:
                    user = self.bot.get_user(r["user_id"])
                    name = user.mention if user else f"<@{r['user_id']}>"
                    await channel.send(f"{name} recordatorio: {r['message']}")
            except Exception:
                pass
            await db.delete_reminder(r["id"])

    @check_giveaways.before_loop
    async def before_giveaways(self):
        await self.bot.wait_until_ready()

    @check_reminders.before_loop
    async def before_reminders(self):
        await self.bot.wait_until_ready()


async def setup(bot):
    await bot.add_cog(CommunityCog(bot))
