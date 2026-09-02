import discord
from discord import app_commands
from discord.ext import commands, tasks
import logging
import random
import time

from ..services import database as db

logger = logging.getLogger("OmniBot.levels")

LEVEL_ROLES = {
    5: ("🔥 Activo", 0xE74C3C),
    10: ("⭐ Veterano", 0xF39C12),
    20: ("👑 Leyenda", 0x9B59B6),
    30: ("💎 Élite", 0x1ABC9C),
}

VOICE_XP_INTERVAL = 300
VOICE_XP_AMOUNT = 20


class LevelsCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self._voice_sessions = {}

    async def cog_load(self):
        self.voice_xp_loop.start()

    async def cog_unload(self):
        self.voice_xp_loop.cancel()

    @commands.Cog.listener()
    async def on_message(self, message):
        if message.author.bot or message.guild is None:
            return

        xp_amount = random.randint(15, 25)
        result = await db.add_xp(message.author.id, xp_amount)

        if result["gained"] and result["leveled_up"]:
            await self._announce_level(message, result)

    @commands.Cog.listener()
    async def on_voice_state_update(self, member, before, after):
        if member.bot:
            return

        if before.channel is None and after.channel is not None:
            self._voice_sessions[member.id] = time.time()

        elif before.channel is not None and after.channel is None:
            if member.id in self._voice_sessions:
                self._voice_sessions.pop(member.id)

    @tasks.loop(seconds=VOICE_XP_INTERVAL)
    async def voice_xp_loop(self):
        try:
            for member_id, start in list(self._voice_sessions.items()):
                elapsed = time.time() - start
                if elapsed < VOICE_XP_INTERVAL:
                    continue
                for guild in self.bot.guilds:
                    member = guild.get_member(member_id)
                    if member and member.voice and member.voice.channel:
                        result = await db.add_voice_xp(member_id, VOICE_XP_AMOUNT)
                        if result.get("leveled_up"):
                            await self._announce_voice_level(member, result)
                        break
                self._voice_sessions[member_id] = time.time()
        except Exception as e:
            logger.error(f"Voice XP loop error: {e}", exc_info=True)
            await self.bot.report_task_error("voice_xp_loop", e)

    @voice_xp_loop.before_loop
    async def before_voice_xp_loop(self):
        await self.bot.wait_until_ready()

    async def _announce_voice_level(self, member, result):
        channel = member.guild.system_channel
        if not channel:
            return
        embed = discord.Embed(
            title="🎉 ¡Subiste de nivel!",
            description=(
                f"{member.mention} alcanzó **Nivel {result['level']}** "
                f"por actividad en voz."
            ),
            color=discord.Color.gold()
        )
        try:
            await channel.send(embed=embed)
        except discord.Forbidden:
            pass

    async def _announce_level(self, message, result):
        level = result["level"]

        embed = discord.Embed(
            title="🎉 ¡Subiste de nivel!",
            description=(
                f"**{message.author.display_name}** alcanzó **Nivel {level}**\n"
                f"XP total: {result['xp']} | +{result['amount']} XP"
            ),
            color=discord.Color.gold()
        )
        embed.set_thumbnail(url=message.author.display_avatar.url)

        try:
            await message.channel.send(embed=embed)
        except discord.Forbidden:
            pass

        try:
            dm_embed = discord.Embed(
                title=f"🎉 ¡Nivel {level}!",
                description=(
                    f"¡Felicidades! Has alcanzado el **Nivel {level}** en **OmniBot**.\n\n"
                    f"XP acumulado: {result['xp']}\n"
                    f"Sigue participando para subir más."
                ),
                color=discord.Color.gold()
            )
            dm_embed.set_thumbnail(url=message.author.display_avatar.url)
            await message.author.send(embed=dm_embed)
        except (discord.Forbidden, discord.HTTPException):
            pass

        await self._check_role_reward(message.author, level)

    async def _check_role_reward(self, member, level):
        for req_level, (role_name, color) in sorted(LEVEL_ROLES.items()):
            if level >= req_level:
                role = discord.utils.get(member.guild.roles, name=role_name)
                if not role:
                    try:
                        role = await member.guild.create_role(
                            name=role_name, color=discord.Color(color)
                        )
                        await role.edit(position=member.guild.roles.index(
                            discord.utils.get(member.guild.roles, name="🛡️ Staff Helper") or member.guild.default_role
                        ) - 1)
                    except discord.Forbidden:
                        continue

                if role and role not in member.roles:
                    try:
                        await member.add_roles(role, reason=f"Nivel {level}")
                    except discord.Forbidden:
                        pass

    @app_commands.command(name="rank", description="Ver tu nivel y XP")
    @app_commands.describe(member="Usuario a consultar (opcional)")
    async def rank_cmd(self, interaction: discord.Interaction, member: discord.Member = None):
        member = member or interaction.user
        data = await db.get_level(member.id)
        pos = await db.get_user_rank_position(member.id)

        xp_needed = (data["level"] + 1) ** 2 * 100

        embed = discord.Embed(
            title=f"📊 Perfil de {member.display_name}",
            color=discord.Color.blue()
        )
        embed.set_thumbnail(url=member.display_avatar.url)
        embed.add_field(name="Nivel", value=f"**{data['level']}**", inline=True)
        embed.add_field(name="XP", value=f"**{data['xp']}** / {xp_needed}", inline=True)
        embed.add_field(name="Rank", value=f"**#{pos}** en el servidor", inline=True)

        roles = [r.name for r in member.roles if r.name != "@everyone"]
        if roles:
            embed.add_field(
                name="Roles",
                value=", ".join(roles[:10]) + ("..." if len(roles) > 10 else ""),
                inline=False
            )

        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="top", description="Top 10 del servidor")
    async def leaderboard_cmd(self, interaction: discord.Interaction):
        top = await db.get_leaderboard(10)
        if not top:
            await interaction.response.send_message("No hay datos de niveles aún.")
            return

        medals = ["🥇", "🥈", "🥉"]
        lines = ["🏆 **Leaderboard — Top 10**\n"]

        for i, entry in enumerate(top):
            user = self.bot.get_user(entry["user_id"])
            name = user.display_name if user else f"Usuario {entry['user_id']}"
            medal = medals[i] if i < 3 else f"**#{i+1}**"
            lines.append(f"{medal} **{name}** — Nivel {entry['level']} ({entry['xp']} XP)")

        await interaction.response.send_message("\n".join(lines))

    @app_commands.command(name="xplb", description="Reinicializar la base de datos (solo propietario)")
    async def xplb_cmd(self, interaction: discord.Interaction):
        if interaction.user.id != interaction.guild.owner_id:
            await interaction.response.send_message("Solo el **PROPIETARIO** puede usar este comando.")
            return
        await db.init_db()
        await interaction.response.send_message("✅ Base de datos reinicializada.")


async def setup(bot):
    await bot.add_cog(LevelsCog(bot))
