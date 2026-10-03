import logging
from datetime import timedelta

import discord

from ..services.authorization import authorize_action, resolve_text_channel
from ..services import database as db
from ..services import modlog
from ..utils.helpers import parse_duration
from ..utils.members import resolve_member

logger = logging.getLogger("OmniBot.tools")
MAX_TIMEOUT_SECONDS = 28 * 86400
MEMBER_ACTIONS = {"warn_user", "mute_user", "unmute_user"}


async def prepare_action(message, action, params):
    guild = message.guild
    if not guild:
        return None, None, None, "Esta acción solo funciona en un servidor."
    try:
        actor = await guild.fetch_member(message.author.id)
        target = None
        if action in MEMBER_ACTIONS:
            resolved = resolve_member(guild, params.get("user", ""))
            if not resolved:
                return None, None, None, "Usuario inexistente o ambiguo. Usa una mención o ID exacto."
            target = await guild.fetch_member(resolved.id)
        channel = resolve_text_channel(guild, params.get("channel", ""), message.channel)
        if not channel:
            return None, None, None, "Canal inexistente, ambiguo o no compatible."
        error = authorize_action(actor, guild, action, target=target, channel=channel)
        return actor, target, channel, error
    except discord.HTTPException:
        return None, None, None, "No pude verificar los miembros actuales. La acción se canceló."


async def _log(message, actor, target_id, action, reason):
    await db.log_mod_action(target_id, action, actor.id, reason, guild_id=message.guild.id)
    await modlog.log_action(message.guild, action=action, target_id=target_id, moderator_id=actor.id, reason=reason)


async def warn_user(bot, message, params: dict) -> str:
    actor, member, _, error = await prepare_action(message, "warn_user", params)
    if error:
        return error
    reason = params.get("reason", "Sin motivo especificado")
    warning = await db.add_warning(member.id, actor.id, reason, guild_id=message.guild.id)
    await _log(message, actor, member.id, "WARN", reason)
    return f"{member.mention} advertido. Razón: {reason} (Warns activos: {warning['total_active']})"


async def mute_user(bot, message, params: dict) -> str:
    actor, member, _, error = await prepare_action(message, "mute_user", params)
    if error:
        return error
    duration = params.get("duration", "10m")
    seconds = parse_duration(duration)
    if not 0 < seconds <= MAX_TIMEOUT_SECONDS:
        return "Duración inválida. Debe ser mayor a cero y como máximo 28d."
    reason = params.get("reason", "Sin motivo")
    await member.timeout(timedelta(seconds=seconds), reason=reason)
    await _log(message, actor, member.id, "MUTE", reason)
    return f"🔇 {member.mention} silenciado por {duration}. Razón: {reason}"


async def unmute_user(bot, message, params: dict) -> str:
    actor, member, _, error = await prepare_action(message, "unmute_user", params)
    if error:
        return error
    await member.timeout(None, reason=f"Desilenciado por {actor}")
    await _log(message, actor, member.id, "UNMUTE", "Desilenciado")
    return f"🔊 {member.mention} desilenciado."


async def clear_messages(bot, message, params: dict) -> str:
    actor, _, channel, error = await prepare_action(message, "clear_messages", params)
    if error:
        return error
    count = params.get("count", 10)
    if type(count) is not int or not 1 <= count <= 100:
        return "Cantidad inválida (1–100)."
    deleted = await channel.purge(limit=count)
    await _log(message, actor, channel.id, "CLEAR_MESSAGES", f"Deleted {len(deleted)} messages in #{channel.name}")
    return f"🧹 Eliminados {len(deleted)} mensajes en {channel.mention}."


async def set_slowmode(bot, message, params: dict) -> str:
    actor, _, channel, error = await prepare_action(message, "set_slowmode", params)
    if error:
        return error
    seconds = params.get("seconds", 0)
    if type(seconds) is not int or not 0 <= seconds <= 21600:
        return "Slowmode inválido (0–21600 segundos)."
    await channel.edit(slowmode_delay=seconds, reason=f"Solicitado por {actor}")
    await _log(message, actor, channel.id, "SET_SLOWMODE", f"Slowmode {seconds}s in #{channel.name}")
    return f"⏱️ Slowmode de {channel.mention}: {seconds}s."
