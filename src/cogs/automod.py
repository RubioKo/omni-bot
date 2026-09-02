import discord
from discord import app_commands
from discord.ext import commands
import logging
import re
import time
from datetime import datetime, timedelta
from urllib.parse import urlparse

from ..config import config, is_staff
from ..services import database as db
from ..services import modlog as modlog_service
from ..services.permissions import permission_manager

logger = logging.getLogger("OmniBot.automod")

SPAM_THRESHOLD = 5
SPAM_WINDOW = 10.0
AUTO_PUNISH_COOLDOWN = 60.0

MASS_MENTION_THRESHOLD = 5
CAPS_MIN_LENGTH = 10
CAPS_RATIO = 0.7
EMOJI_SPAM_THRESHOLD = 8

SAFE_DOMAINS = {
    "youtube.com", "youtu.be", "discord.com", "discord.gg", "discordapp.com",
    "twitch.tv", "twitter.com", "x.com",
    "reddit.com", "imgur.com",
    "github.com", "spotify.com",
    "tiktok.com", "instagram.com", "facebook.com",
}

MUTE_DURATIONS = [300, 1800, 3600]

RAID_THRESHOLD = 5
RAID_WINDOW = 30.0

MAX_TIMEOUT_SECONDS = 28 * 86400

BANNED_WORDS_DEFAULT = [
    "puta", "puto", "putita", "mierda", "marica", "maricón", "maricon",
    "pendejo", "pendeja", "idiota", "estúpido", "estupido", "estúpida",
    "conchetumadre", "concha de tu madre", "culiao", "culiado", "pelotudo",
    "pelotuda", "hijueputa", "hijo de puta", "verga", "forro", "trolo",
    "mogolico", "mogólico", "retrasado", "retrasada", "cabrón", "cabron",
    "picha", "malparido", "malparida", "gonorrea",
]

LEET_MAP = str.maketrans({"0": "o", "1": "i", "3": "e", "4": "a", "5": "s", "7": "t", "@": "a", "$": "s"})

MENTION_RE = re.compile(r"<@[!&]?\d+>")
EMOJI_RE = re.compile(r"[\U0001F300-\U0001FAFF\u2600-\u27BF]|<a?:\w+:\d+>")
URL_RE = re.compile(r'https?://[^\s]+|www\.[^\s]+|discord\.gg/[^\s]+', re.IGNORECASE)

_banned_regex_cache = {}


def normalize_text(text: str) -> str:
    lowered = text.lower().translate(LEET_MAP)
    return re.sub(r"\s+", " ", lowered).strip()


def get_banned_words() -> list:
    extra = [w.strip().lower() for w in (config.banned_words or "").split(",") if w.strip()]
    return BANNED_WORDS_DEFAULT + extra


def contains_banned_word(content: str, words: list | None = None) -> bool:
    if not words:
        words = get_banned_words()
    norm = normalize_text(content)
    phrases = [w for w in words if " " in w]
    singles = [w for w in words if " " not in w]
    if any(p in norm for p in phrases):
        return True
    if not singles:
        return False
    key = tuple(sorted(singles))
    pattern = _banned_regex_cache.get(key)
    if pattern is None:
        pattern = re.compile(r"\b(?:" + "|".join(re.escape(w) for w in singles) + r")\b")
        _banned_regex_cache[key] = pattern
    return bool(pattern.search(norm))


def count_mentions(content: str) -> int:
    return len(MENTION_RE.findall(content))


def is_excessive_caps(content: str, min_length: int = CAPS_MIN_LENGTH, ratio: float = CAPS_RATIO) -> bool:
    letters = [c for c in content if c.isalpha()]
    if len(letters) < min_length:
        return False
    uppers = sum(1 for c in letters if c.isupper())
    return uppers / len(letters) > ratio


def count_emojis(content: str) -> int:
    return len(EMOJI_RE.findall(content))


def should_flag_new_account(created_at, min_days: int = 7, now=None) -> bool:
    if created_at is None:
        return False
    if now is None:
        now = discord.utils.utcnow()
    return (now - created_at).total_seconds() < min_days * 86400


class AutoModCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.joins = {}
        self._last_punished = {}

    def _is_staff(self, member: discord.Member) -> bool:
        return is_staff(member)

    def _get_help_channel(self, guild: discord.Guild):
        for name in ("sugerencias", "staff", "mod-log"):
            ch = discord.utils.get(guild.text_channels, name=name)
            if ch:
                return ch.mention
        return "al staff"

    async def _get_mute_duration(self, user_id: int) -> int:
        warnings = await db.get_active_warnings(user_id)
        count = max(len(warnings), 1)
        idx = min(count - 1, len(MUTE_DURATIONS) - 1)
        return MUTE_DURATIONS[idx]

    @commands.Cog.listener()
    async def on_message(self, message):
        if message.author.bot or message.guild is None:
            return
        if self._is_staff(message.author):
            return

        for check in (
            self._check_spam,
            self._check_links,
            self._check_banned_words,
            self._check_mass_mention,
            self._check_caps,
            self._check_emoji_spam,
        ):
            try:
                await check(message)
            except Exception as e:
                logger.error(f"Auto-mod check {check.__name__} falló: {e}", exc_info=True)

    async def _auto_punish(self, message, category: str, reason_prefix: str):
        now = time.time()
        if now - self._last_punished.get(message.author.id, 0) < AUTO_PUNISH_COOLDOWN:
            return
        self._last_punished[message.author.id] = now

        try:
            await message.delete()
        except (discord.NotFound, discord.Forbidden):
            pass

        reason = f"Auto-mod: {reason_prefix}"
        warning = await db.add_warning(message.author.id, self.bot.user.id, reason)
        await db.log_mod_action(message.author.id, category, self.bot.user.id, reason)
        await modlog_service.log_action(
            message.guild,
            action=category,
            target_id=message.author.id,
            moderator_id=self.bot.user.id,
            reason=reason,
        )

        total = warning["total_active"]
        mute_duration = min(await self._get_mute_duration(message.author.id), MAX_TIMEOUT_SECONDS)

        try:
            await message.author.timeout(
                discord.utils.utcnow() + timedelta(seconds=mute_duration),
                reason=reason,
            )
            mins = mute_duration // 60
            embed = discord.Embed(
                title="🔇 Silenciado por auto-mod",
                description=(
                    f"{message.author.mention} fue silenciado por **{mins} minutos**.\n"
                    f"Razón: {reason_prefix}.\n"
                    f"Warns activos: {total}"
                ),
                color=discord.Color.orange(),
            )
            await message.channel.send(embed=embed, delete_after=10)
        except discord.Forbidden:
            embed = discord.Embed(
                title="⚠️ Advertencia",
                description=(
                    f"{message.author.mention}, detente. Motivo: {reason_prefix}.\n"
                    f"Warns activos: {total}"
                ),
                color=discord.Color.yellow(),
            )
            await message.channel.send(embed=embed, delete_after=10)

        logger.info(f"{category}: {message.author} in #{message.channel} - {reason_prefix}")

    async def _check_spam(self, message):
        count = await db.track_spam(message.author.id, message.channel.id, SPAM_WINDOW)
        if count >= SPAM_THRESHOLD:
            await self._auto_punish(
                message, "SPAM", f"Anti-spam: {count} mensajes en {int(SPAM_WINDOW)}s"
            )

    async def _check_links(self, message):
        urls = URL_RE.findall(message.content)

        if not urls:
            return

        for url in urls:
            domain = self._extract_domain(url)
            if self._is_safe_domain(domain):
                continue

            try:
                await message.delete()
            except (discord.NotFound, discord.Forbidden):
                pass

            await modlog_service.log_action(
                message.guild,
                action="LINK_BLOCKED",
                target_id=message.author.id,
                moderator_id=self.bot.user.id,
                reason=f"Link externo bloqueado: {domain}",
            )

            embed = discord.Embed(
                title="🔗 Link requiere aprobación",
                description=(
                    f"{message.author.mention}, los links externos requieren "
                    f"aprobación del staff.\n\n"
                    f"Si necesitas compartir este link, pide permiso en {self._get_help_channel(message.guild)}."
                ),
                color=discord.Color.orange()
            )
            await message.channel.send(embed=embed, delete_after=15)
            logger.info(f"Link blocked: {message.author} posted {domain}")
            break

    async def _check_banned_words(self, message):
        words = get_banned_words()
        if not words:
            return
        if contains_banned_word(message.content, words):
            await self._auto_punish(message, "WORD_FILTER", "Lenguaje inapropiado")

    async def _check_mass_mention(self, message):
        if count_mentions(message.content) >= MASS_MENTION_THRESHOLD:
            await self._auto_punish(message, "MASS_PING", "Menciones masivas")

    async def _check_caps(self, message):
        if is_excessive_caps(message.content):
            await self._auto_punish(message, "CAPS", "Uso excesivo de mayúsculas")

    async def _check_emoji_spam(self, message):
        if count_emojis(message.content) >= EMOJI_SPAM_THRESHOLD:
            await self._auto_punish(message, "EMOJI_SPAM", "Spam de emojis")

    def _extract_domain(self, url: str) -> str:
        if not url or not isinstance(url, str):
            return ""
        url = url.strip().lower()
        if " " in url:
            return ""
        if not url.startswith(("http://", "https://")):
            url = "https://" + url
        try:
            host = urlparse(url).hostname or ""
        except ValueError:
            host = ""
        return host.removeprefix("www.")

    def _is_safe_domain(self, domain: str) -> bool:
        if not domain:
            return True
        return any(domain == d or domain.endswith("." + d) for d in SAFE_DOMAINS)

    @commands.Cog.listener()
    async def on_member_join(self, member):
        now = time.time()
        guild_id = member.guild.id
        joins = self.joins.setdefault(guild_id, [])
        joins.append(now)

        self.joins[guild_id] = [t for t in joins if now - t < RAID_WINDOW]

        if should_flag_new_account(member.created_at, config.min_account_age_days):
            await modlog_service.log_action(
                member.guild,
                action="NEW_ACCOUNT_FLAG",
                target_id=member.id,
                moderator_id=self.bot.user.id,
                reason=(
                    f"Cuenta creada el {member.created_at:%d/%m/%Y} "
                    f"(< {config.min_account_age_days} días)"
                ),
            )
            logger.info(f"New account flagged: {member} (created {member.created_at})")

        if len(self.joins[guild_id]) >= RAID_THRESHOLD:
            await self._alert_raid(member.guild)
            if config.raid_auto_lockdown:
                await self._auto_lockdown(member.guild)
            self.joins[guild_id].clear()

    async def _auto_lockdown(self, guild: discord.Guild):
        everyone = guild.default_role
        if not everyone.permissions.send_messages:
            return
        try:
            await everyone.edit(send_messages=False)
            await modlog_service.log_action(
                guild,
                action="RAID_LOCKDOWN",
                target_id=guild.id,
                moderator_id=self.bot.user.id,
                reason="Bloqueo automático de canales por raid detectado",
            )
            logger.warning(f"Auto-lockdown activated in {guild.name} (raid detected)")
        except discord.Forbidden:
            logger.warning(f"No permissions to auto-lockdown {guild.name}")

    async def _alert_raid(self, guild):
        staff_channel = None
        for ch in guild.text_channels:
            if "staff" in ch.name.lower() or "mod" in ch.name.lower():
                staff_channel = ch
                break

        if not staff_channel:
            staff_channel = guild.system_channel
            if not staff_channel and guild.text_channels:
                staff_channel = guild.text_channels[0]

        if not staff_channel:
            return

        embed = discord.Embed(
            title="🚨 ALERTA DE RAID",
            description=(
                f"Se detectaron **{RAID_THRESHOLD}+ entradas** en los últimos "
                f"{int(RAID_WINDOW)} segundos.\n\n"
                f"**Acción recomendada:**\n"
                f"• Revisa los miembros recientes\n"
                f"• Usa `/lockdown` para desbloquear cuando termine"
            ),
            color=discord.Color.red()
        )
        embed.set_footer(text="Auto-mod Anti-Raid")

        try:
            await staff_channel.send(
                content="@here ¡Posible raid detectado!",
                embed=embed
            )
        except discord.Forbidden:
            pass

        logger.warning(f"RAID detected in {guild.name}: {RAID_THRESHOLD}+ joins in {RAID_WINDOW}s")

    async def _check_hierarchy(self, interaction: discord.Interaction, member: discord.Member) -> bool:
        guild = interaction.guild
        if member.id == guild.owner_id:
            await interaction.followup.send("No puedes sancionar al propietario del servidor.")
            return False
        if member.top_role >= interaction.user.top_role and interaction.user.id != guild.owner_id:
            await interaction.followup.send("No puedes sancionar a un miembro con rol igual o superior al tuyo.")
            return False
        if member.top_role >= guild.me.top_role:
            await interaction.followup.send("No puedo sancionar a un miembro con rol igual o superior al mío.")
            return False
        return True

    @app_commands.command(name="warnings", description="Ver advertencias de un miembro")
    @app_commands.describe(member="Miembro a consultar")
    async def warnings_cmd(self, interaction: discord.Interaction, member: discord.Member):
        if not permission_manager.has_permission(interaction.user, "warn_user"):
            await interaction.response.send_message("Necesitas permisos de **MODERADOR** para usar este comando.")
            return
        warns = await db.get_active_warnings(member.id)
        if not warns:
            await interaction.response.send_message(f"✅ {member.mention} no tiene warnings activos.")
            return

        lines = [f"⚠️ **Warnings de {member.display_name}** ({len(warns)} activos)\n"]
        for w in warns[:10]:
            ts = datetime.fromtimestamp(w["created_at"]).strftime("%d/%m %H:%M")
            lines.append(f"• {ts} — {w['reason']}")
        await interaction.response.send_message("\n".join(lines))

    @app_commands.command(name="clearwarnings", description="Limpiar advertencias de un miembro")
    @app_commands.describe(member="Miembro a limpiar")
    async def clearwarnings_cmd(self, interaction: discord.Interaction, member: discord.Member):
        if not permission_manager.has_permission(interaction.user, "clearwarnings"):
            await interaction.response.send_message("Necesitas permisos de **MODERADOR** para usar este comando.")
            return
        count = await db.clear_warnings(member.id)
        await db.log_mod_action(member.id, "CLEAR_WARNINGS", interaction.user.id, f"Cleared {count} warnings")
        await modlog_service.log_action(
            interaction.guild,
            action="CLEAR_WARNINGS",
            target_id=member.id,
            moderator_id=interaction.user.id,
            reason=f"Se limpiaron {count} warnings",
        )
        await interaction.response.send_message(f"✅ Se limpiaron **{count} warnings** de {member.mention}.")

    @app_commands.command(name="modlog", description="Ver registro de moderacion")
    @app_commands.describe(limit="Numero de entradas (default 10)")
    async def modlog_cmd(self, interaction: discord.Interaction, limit: int = 10):
        if not permission_manager.has_permission(interaction.user, "warn_user"):
            await interaction.response.send_message("Necesitas permisos de **MODERADOR** para usar este comando.")
            return
        limit = min(max(limit, 1), 50)
        logs = await db.get_modlog(limit)
        if not logs:
            await interaction.response.send_message("📋 No hay acciones de moderación recientes.")
            return

        lines = [f"📋 **Últimas {len(logs)} acciones de moderación**\n"]
        for log in logs:
            ts = datetime.fromtimestamp(log["created_at"]).strftime("%d/%m %H:%M")
            user = self.bot.get_user(log["user_id"])
            user_name = user.display_name if user else str(log["user_id"])
            lines.append(f"`{ts}` **{log['action']}** — {user_name} — {log['reason'][:50]}")
        await interaction.response.send_message("\n".join(lines))

    @app_commands.command(name="modwords", description="Ver palabras filtradas (MOD+)")
    async def modwords_cmd(self, interaction: discord.Interaction):
        if not permission_manager.has_permission(interaction.user, "warn_user"):
            await interaction.response.send_message("Necesitas permisos de **MODERADOR** para usar este comando.")
            return
        words = get_banned_words()
        if not words:
            await interaction.response.send_message("No hay palabras filtradas.")
            return
        await interaction.response.send_message(f"📋 **Palabras filtradas ({len(words)})**:\n```{', '.join(words)}```")

    @app_commands.command(name="kick", description="Expulsar un miembro del servidor")
    @app_commands.describe(member="Miembro a expulsar", reason="Motivo de la expulsion")
    async def kick_cmd(self, interaction: discord.Interaction, member: discord.Member, *, reason: str = "Sin razon"):
        if not permission_manager.has_permission(interaction.user, "kick_user"):
            await interaction.response.send_message("Solo **MODERADOR** o superior puede usar este comando.")
            return
        await interaction.response.defer()
        if not await self._check_hierarchy(interaction, member):
            return
        try:
            await member.kick(reason=reason)
            await db.log_mod_action(member.id, "KICK", interaction.user.id, reason)
            await modlog_service.log_action(
                interaction.guild, action="KICK", target_id=member.id,
                moderator_id=interaction.user.id, reason=reason,
            )
            await interaction.followup.send(f"{member.mention} expulsado. Razon: {reason}")
        except discord.Forbidden:
            await interaction.followup.send("No tengo permisos para expulsar a ese miembro.")
        except Exception as e:
            logger.error(f"Kick error: {e}")
            await interaction.followup.send("Ocurrio un error al expulsar al miembro.")

    @app_commands.command(name="ban", description="Banear un miembro del servidor")
    @app_commands.describe(member="Miembro a banear", reason="Motivo del baneo")
    async def ban_cmd(self, interaction: discord.Interaction, member: discord.Member, *, reason: str = "Sin razon"):
        if not permission_manager.has_permission(interaction.user, "ban_user"):
            await interaction.response.send_message("Solo **MODERADOR** o superior puede usar este comando.")
            return
        await interaction.response.defer()
        if not await self._check_hierarchy(interaction, member):
            return
        try:
            await member.ban(reason=reason, delete_message_seconds=86400)
            await db.log_mod_action(member.id, "BAN", interaction.user.id, reason)
            await modlog_service.log_action(
                interaction.guild, action="BAN", target_id=member.id,
                moderator_id=interaction.user.id, reason=reason,
            )
            await interaction.followup.send(f"{member.mention} baneado. Razon: {reason}")
        except discord.Forbidden:
            await interaction.followup.send("No tengo permisos para banear a ese miembro.")
        except Exception as e:
            logger.error(f"Ban error: {e}")
            await interaction.followup.send("Ocurrio un error al banear al miembro.")

    @app_commands.command(name="unban", description="Desbanear un usuario por ID")
    @app_commands.describe(user_id="ID del usuario a desbanear")
    async def unban_cmd(self, interaction: discord.Interaction, user_id: str):
        if not permission_manager.has_permission(interaction.user, "ban_user"):
            await interaction.response.send_message("Solo **MODERADOR** o superior puede usar este comando.")
            return
        try:
            uid = int(user_id)
            user = await self.bot.fetch_user(uid)
            await interaction.guild.unban(user)
            await db.log_mod_action(uid, "UNBAN", interaction.user.id, "Desbaneado")
            await modlog_service.log_action(
                interaction.guild, action="UNBAN", target_id=uid,
                moderator_id=interaction.user.id, reason="Desbaneado",
            )
            await interaction.response.send_message(f"{user.name} desbaneado.")
        except ValueError:
            await interaction.response.send_message("ID de usuario invalido.")
        except discord.NotFound:
            await interaction.response.send_message("Usuario no encontrado o no esta baneado.")
        except Exception as e:
            logger.error(f"Unban error: {e}")
            await interaction.response.send_message("Ocurrio un error al desbanear al usuario.")

    @app_commands.command(name="lockdown", description="Bloquear/desbloquear canales del servidor")
    async def lockdown_cmd(self, interaction: discord.Interaction):
        if not permission_manager.has_permission(interaction.user, "lockdown"):
            await interaction.response.send_message("Necesitas permisos de **MODERADOR** para usar este comando.")
            return
        guild = interaction.guild
        everyone = guild.default_role
        current = everyone.permissions.send_messages

        await everyone.edit(send_messages=not current)
        state = "🔴 BLOQUEADO" if current else "🟢 DESBLOQUEADO"
        await modlog_service.log_action(
            interaction.guild,
            action="LOCKDOWN" if current else "UNLOCKDOWN",
            target_id=guild.id,
            moderator_id=interaction.user.id,
            reason="Canales bloqueados" if current else "Canales desbloqueados",
        )
        await interaction.response.send_message(f"{state} — Los canales de texto han sido {'bloqueados' if current else 'desbloqueados'}.")


async def setup(bot):
    await bot.add_cog(AutoModCog(bot))
