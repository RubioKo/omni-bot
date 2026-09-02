import logging
from datetime import timedelta

from ..utils.helpers import parse_duration
from ..utils.members import resolve_member

logger = logging.getLogger("OmniBot.tools")

MAX_TIMEOUT_SECONDS = 28 * 86400


def _resolve_member(message, user_str: str):
    if not message.guild:
        return None
    return resolve_member(message.guild, user_str)


async def warn_user(bot, message, params: dict) -> str:
    user_str = params.get("user", "")
    reason = params.get("reason", "Sin motivo especificado")
    member = _resolve_member(message, user_str)
    if not member:
        return f"No encontre al usuario {user_str}"
    try:
        from ..services import database as db
        warning = await db.add_warning(member.id, message.author.id, reason)
        await db.log_mod_action(member.id, "WARN", message.author.id, reason)
        logger.info(f"WARN {member} | Razon: {reason} | Moderador: {message.author} | Total: {warning['total_active']}")
        return f"{member.mention} advertido. Razon: {reason} (Warns activos: {warning['total_active']})"
    except Exception as e:
        logger.error(f"Warn error: {e}")
        return "Error al advertir. Revisa los logs."


async def mute_user(bot, message, params: dict) -> str:
    user_str = params.get("user", "")
    duration_str = params.get("duration", "10m")
    reason = params.get("reason", "Sin motivo")
    member = _resolve_member(message, user_str)
    if not member:
        return f"No encontré al usuario {user_str}"
    seconds = parse_duration(duration_str)
    if seconds <= 0:
        return "Duración inválida. Usa ej: 10m, 1h, 2d"
    if seconds > MAX_TIMEOUT_SECONDS:
        seconds = MAX_TIMEOUT_SECONDS
        duration_str = "28d"
    try:
        from ..services import database as db
        await member.timeout(timedelta(seconds=seconds), reason=reason)
        await db.log_mod_action(member.id, "MUTE", message.author.id, reason)
        logger.info(f"MUTE {member} | Duracion: {duration_str} | Moderador: {message.author}")
        return f"🔇 {member.mention} silenciado por {duration_str}. Razón: {reason}"
    except Exception as e:
        logger.error(f"Mute error: {e}")
        return "Error al silenciar. Revisa los logs."


async def unmute_user(bot, message, params: dict) -> str:
    user_str = params.get("user", "")
    member = _resolve_member(message, user_str)
    if not member:
        return f"No encontré al usuario {user_str}"
    try:
        from ..services import database as db
        await member.timeout(None, reason=f"Desilenciado por {message.author}")
        await db.log_mod_action(member.id, "UNMUTE", message.author.id, "Desilenciado")
        return f"🔊 {member.mention} desilenciado."
    except Exception as e:
        logger.error(f"Unmute error: {e}")
        return "Error al desilenciar. Revisa los logs."


async def clear_messages(bot, message, params: dict) -> str:
    count = min(int(params.get("count", 10)), 100)
    try:
        from ..services import database as db
        deleted = await message.channel.purge(limit=count)
        await db.log_mod_action(
            message.channel.id, "CLEAR_MESSAGES", message.author.id,
            f"Deleted {len(deleted)} messages in #{message.channel.name}"
        )
        return f"🧹 Eliminados {len(deleted)} mensajes."
    except Exception as e:
        logger.error(f"Clear messages error: {e}")
        return "Error al limpiar. Revisa los logs."


async def set_slowmode(bot, message, params: dict) -> str:
    seconds = int(params.get("seconds", 0))
    channel_str = params.get("channel", "")
    channel = message.channel
    if channel_str:
        for c in message.guild.channels:
            if channel_str.lower() in c.name.lower():
                channel = c
                break
    try:
        from ..services import database as db
        await channel.edit(slowmode_delay=seconds)
        await db.log_mod_action(
            channel.id, "SET_SLOWMODE", message.author.id,
            f"Slowmode {seconds}s in #{channel.name}"
        )
        if seconds == 0:
            return f"⏱️ Slowmode desactivado en {channel.mention}."
        return f"⏱️ Slowmode activado en {channel.mention} ({seconds}s entre mensajes)."
    except Exception as e:
        logger.error(f"Slowmode error: {e}")
        return "Error al cambiar slowmode. Revisa los logs."
