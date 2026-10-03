import json
from datetime import datetime, timezone

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

    @app_commands.guild_only()
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

    @app_commands.guild_only()
    @app_commands.command(name="giveaway", description="Iniciar un sorteo (MOD+)")
    @app_commands.describe(premio="Que se sortea", duracion="Ej: 1h, 30m, 2d", ganadores="Cuantos ganan (default 1)")
    async def giveaway_cmd(self, interaction: discord.Interaction, premio: app_commands.Range[str, 1, 200], duracion: str, ganadores: int = 1):
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

    @app_commands.guild_only()
    @app_commands.command(name="remind", description="Programar un recordatorio")
    @app_commands.describe(tiempo="Ej: 10m, 2h, 1d", mensaje="Que quieres recordar")
    async def remind_cmd(self, interaction: discord.Interaction, tiempo: str, *, mensaje: app_commands.Range[str, 1, 1500]):
        seconds = parse_duration(tiempo)
        if seconds < 30 or seconds > 2592000:
            await interaction.response.send_message("Tiempo invalido. Debe ser entre 30 segundos y 30 dias. Ej: 10m, 2h, 1d")
            return

        remind_at = time.time() + seconds
        await db.create_reminder(interaction.user.id, interaction.channel.id, mensaje, remind_at, guild_id=interaction.guild.id)

        ts = f"<t:{int(remind_at)}:R>"
        await interaction.response.send_message(f"Te avisare {ts}: {mensaje}", ephemeral=True)

    @tasks.loop(seconds=30)
    async def check_giveaways(self):
        try:
            await self._check_giveaways()
        except Exception as e:
            logger.error(f"Giveaway loop error: {e}", exc_info=True)
            await self.bot.report_task_error("check_giveaways", e)

    async def _send_delivery(self, channel, marker, content, due_at, user_ids):
        after = datetime.fromtimestamp(due_at, tz=timezone.utc)
        async for message in channel.history(limit=None, after=after):
            if message.author.id == self.bot.user.id and any(e.footer.text == marker for e in message.embeds):
                return
        embed = discord.Embed(description=content, color=0x57F287)
        embed.set_footer(text=marker)
        await channel.send(embed=embed, allowed_mentions=discord.AllowedMentions(
            everyone=False, roles=False, users=[discord.Object(id=uid) for uid in user_ids],
        ))

    async def _check_giveaways(self):
        for gw in await db.get_active_giveaways():
            try:
                guild = self.bot.get_guild(gw["guild_id"])
                channel = guild.get_channel(gw["channel_id"]) if guild else None
                if channel is None:
                    raise RuntimeError("Canal de sorteo no disponible")
                if gw["result"] is None:
                    message = await channel.fetch_message(gw["message_id"])
                    reaction = next((r for r in message.reactions if str(r.emoji) == GIVEAWAY_EMOJI), None)
                    users = [u async for u in reaction.users() if not u.bot] if reaction else []
                    winners = random.sample(users, min(gw["winners"], len(users)))
                    winner_ids = await db.save_giveaway_result(gw["id"], [u.id for u in winners])
                else:
                    winner_ids = json.loads(gw["result"])
                winner_text = ", ".join(f"<@{uid}>" for uid in winner_ids) or "No hubo participantes."
                content = f"🎉 **SORTEO FINALIZADO**\nPremio: **{gw['prize']}**\nGanador(es): {winner_text}\nOrganizado por <@{gw['created_by']}>"
                await self._send_delivery(channel, f"omnibot:giveaway:{gw['guild_id']}:{gw['id']}", content, gw["ends_at"], winner_ids)
                await db.end_giveaway(gw["id"])
            except Exception as error:
                logger.exception("Sorteo %s pendiente de reintento", gw["id"])
                await db.retry_delivery("giveaways", gw["id"], type(error).__name__)
                await self.bot.report_task_error("check_giveaways", error)

    @tasks.loop(seconds=30)
    async def check_reminders(self):
        try:
            await self._check_reminders()
        except Exception as e:
            logger.error(f"Reminder loop error: {e}", exc_info=True)
            await self.bot.report_task_error("check_reminders", e)

    async def _check_reminders(self):
        for reminder in await db.get_due_reminders():
            try:
                channel = self.bot.get_channel(reminder["channel_id"])
                if channel is None or channel.guild.id != reminder["guild_id"]:
                    raise RuntimeError("Canal de recordatorio no disponible")
                await self._send_delivery(
                    channel, f"omnibot:reminder:{reminder['guild_id']}:{reminder['id']}",
                    f"<@{reminder['user_id']}> recordatorio: {reminder['message']}",
                    reminder["remind_at"], [reminder["user_id"]],
                )
                await db.delete_reminder(reminder["id"])
            except Exception as error:
                logger.exception("Recordatorio %s pendiente de reintento", reminder["id"])
                await db.retry_delivery("reminders", reminder["id"], type(error).__name__)
                await self.bot.report_task_error("check_reminders", error)

    @check_giveaways.before_loop
    async def before_giveaways(self):
        await self.bot.wait_until_data_ready()

    @check_reminders.before_loop
    async def before_reminders(self):
        await self.bot.wait_until_data_ready()


async def setup(bot):
    await bot.add_cog(CommunityCog(bot))
