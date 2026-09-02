import discord
from discord import app_commands
from discord.ext import commands
import logging

from ..services.permissions import permission_manager, PermissionLevel

logger = logging.getLogger("OmniBot.info")


class InfoCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    def _get_meme_channel_ids(self) -> set:
        ids = set()
        for guild in self.bot.guilds:
            ch = discord.utils.get(guild.text_channels, name="memes")
            if ch:
                ids.add(ch.id)
        return ids

    @app_commands.command(name="ping", description="Ver latencia del bot")
    async def ping_cmd(self, interaction: discord.Interaction):
        latency = round(self.bot.latency * 1000)
        await interaction.response.send_message(f"🏓 Pong! Latencia: **{latency}ms**")

    @app_commands.command(name="guia", description="Guia de inicio del servidor")
    async def guia_cmd(self, interaction: discord.Interaction):
        embed = discord.Embed(
            title="📋 OmniBot — Guía de inicio",
            description="Todo lo que necesitas saber para empezar en el servidor.",
            color=0x5865F2
        )

        embed.add_field(
            name="🎮 JUEGOS",
            value="Elige tus juegos en **#roles** con los menús desplegables.\n"
                  "Cada juego desbloquea sus canales automáticamente.",
            inline=False
        )

        embed.add_field(
            name="🎵 MUSICA 24/7",
            value="`/radio rock` — Rock Classics\n"
                  "`/radio lofi` — Radio Lo-Fi\n"
                  "`/radio synthwave` — Synthwave\n"
                  "`/radio chill` — Chill Vibes\n"
                  "`/radio pop` — Pop Hits\n"
                  "`/play <cancion>` — Reproducir cancion\n"
                  "`/radiostop` — Detener radio\n"
                  "`/queue` — Ver cola de reproduccion",
            inline=False
        )

        embed.add_field(
            name="👥 BUSCAR GRUPO",
            value="Usa **#lfg** (Foro) para encontrar grupo por juego.\n"
                  "Elige el tag del juego al crear tu post.",
            inline=False
        )

        embed.add_field(
            name="👥 COMUNIDAD",
            value="**#game-nights** — Organiza noches de juegos\n"
                  "**#coach-corner** — Veteranos ayudan a nuevos\n"
                  "**#sugerencias** — Ideas para mejorar el servidor\n"
                  "**#presentaciones** — Preséntate a la comunidad",
            inline=False
        )

        embed.add_field(
            name="📊 PROGRESIÓN",
            value="`/rank` — Tu nivel actual\n"
                  "`/top` — Top 10 del servidor\n"
                  "Participa en texto y voz para ganar XP y subir de nivel.",
            inline=False
        )

        embed.add_field(
            name="🛡️ STAFF",
            value="¿Problemas o dudas? Menciona a un **@moderador** o usa el canal de staff.",
            inline=False
        )

        embed.set_footer(text="OmniBot | Usa /comandos para ver todos los comandos")
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="reglas", description="Publicar reglas del servidor")
    async def reglas_cmd(self, interaction: discord.Interaction):
        if not permission_manager.has_permission(interaction.user, "reglas"):
            await interaction.response.send_message("Necesitas permisos de **MODERADOR** para usar este comando.")
            return
        from ..services.rules import build_rules_embed
        await interaction.response.send_message(embed=build_rules_embed())

    @app_commands.command(name="comandos", description="Lista de comandos disponibles")
    async def comandos_cmd(self, interaction: discord.Interaction):
        level = permission_manager.get_permission_level(interaction.user)
        embed = discord.Embed(
            title="Comandos de OmniBot",
            description=f"Lista para tu nivel: **{level.name}**",
            color=0x5865F2
        )

        embed.add_field(
            name="Musica (todos)",
            value="`/radio` `/radiostop` `/np` `/queue`",
            inline=False
        )

        if level >= PermissionLevel.DJ:
            embed.add_field(
                name="DJ",
                value="`/play` `/skip` `/stop` `/volume` `/loop` `/pause` `/resume` `/disconnect`",
                inline=False
            )

        embed.add_field(
            name="Niveles",
            value="`/rank` `/top`",
            inline=False
        )

        embed.add_field(
            name="Info",
            value="`/guia` `/comandos` `/ping`",
            inline=False
        )

        embed.add_field(
            name="Comunidad",
            value="`/poll` `/remind`",
            inline=False
        )

        if level >= PermissionLevel.MODERATOR:
            embed.add_field(
                name="Moderacion",
                value="`/warnings` `/modlog` `/kick` `/ban` `/unban` `/meme` `/lockdown` `/clearwarnings` `/reglas`",
                inline=False
            )

            embed.add_field(
                name="Sorteos",
                value="`/giveaway`",
                inline=False
            )

        if level >= PermissionLevel.OWNER:
            embed.add_field(
                name="Propietario",
                value="`/nuke-all` `/deploy` `/server-map` `/restart-bot` `/repostroles` `/xplb`",
                inline=False
            )

        embed.set_footer(text="Usa /guia para la guia completa de inicio")
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="meme", description="Publicar memes del top del día (MOD+)")
    @app_commands.describe(cantidad="Cantidad de memes (1-3, default 1)")
    async def meme_cmd(self, interaction: discord.Interaction, cantidad: int = 1):
        if not permission_manager.has_permission(interaction.user, "warn_user"):
            await interaction.response.send_message("Solo **MODERADOR** o superior puede usar este comando.")
            return

        from datetime import datetime
        await interaction.response.defer()
        from ..services.memes import (
            get_memes,
            get_theme_for_weekday,
            prepare_memes,
            MemeRerollView,
        )
        theme = get_theme_for_weekday(datetime.now().weekday())
        memes = await get_memes(cantidad, theme)

        if not memes:
            await interaction.followup.send("No se encontraron memes. Intenta mas tarde.")
            return

        image_memes = [m for m in memes if not m.get("is_video")]
        video_memes = [m for m in memes if m.get("is_video")]

        embeds, files = await prepare_memes(image_memes)
        view = MemeRerollView()
        if embeds:
            kwargs = {"embeds": embeds, "view": view}
            if files:
                kwargs["files"] = files
            await interaction.followup.send(**kwargs)
        for meme in video_memes:
            await interaction.followup.send(content=f"🎬 **{meme['title']}**\n{meme['url']}")

    @commands.Cog.listener()
    async def on_raw_reaction_add(self, payload):
        await self._handle_meme_reaction(payload, +1)

    @commands.Cog.listener()
    async def on_raw_reaction_remove(self, payload):
        await self._handle_meme_reaction(payload, -1)

    async def _handle_meme_reaction(self, payload, delta: int):
        from ..services.memes import FUNNY_EMOJIS
        from ..services import database as db

        if payload.user_id == self.bot.user.id:
            return
        if str(payload.emoji) not in FUNNY_EMOJIS:
            return
        if payload.channel_id not in self._get_meme_channel_ids():
            return

        try:
            channel = self.bot.get_channel(payload.channel_id)
            if not channel:
                return
            msg = await channel.fetch_message(payload.message_id)
        except Exception:
            return

        if msg.author.id != self.bot.user.id or not msg.embeds:
            return

        embed = msg.embeds[0]
        if embed.title not in ("🤣 MEME DEL DIA", "🏆 MEME DE LA SEMANA"):
            return

        url = embed.image.url
        if not url:
            return

        footer = embed.footer.text or ""
        source = "desconocido"
        import re
        match = re.search(r"r/(\S+)", footer)
        if match:
            source = match.group(1)
        elif "📱" in footer:
            source = footer.split("📱")[1].split("·")[0].strip().lower()

        await db.record_meme_feedback(url, source, delta)


async def setup(bot):
    await bot.add_cog(InfoCog(bot))
