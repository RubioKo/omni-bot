import logging

from ..utils.members import resolve_member

logger = logging.getLogger("OmniBot.tools")

async def get_server_stats(bot, message, params: dict) -> str:
    guild = message.guild
    if not guild:
        return "Este comando solo funciona en un servidor."
    roles = len(guild.roles)
    online = sum(1 for m in guild.members if m.status != "offline")
    text_channels = len(guild.text_channels)
    voice_channels = len(guild.voice_channels)
    total = guild.member_count
    lines = [
        f"👥 **Miembros**: {total} ({online} online)",
        f"💬 **Canales de texto**: {text_channels}",
        f"🔊 **Canales de voz**: {voice_channels}",
        f"🏷️ **Roles**: {roles}",
        f"📅 **Creado**: {guild.created_at.strftime('%d/%m/%Y')}",
    ]
    return "\n".join(lines)

async def get_user_info(bot, message, params: dict) -> str:
    user_str = params.get("user", "")
    if not message.guild:
        return "Este comando solo funciona en un servidor."
    member = resolve_member(message.guild, user_str)
    if not member:
        return f"No encontré al usuario {user_str}"
    lines = [
        f"👤 **{member.name}**",
        f"🆔 ID: {member.id}",
        f"📅 Se unió: {member.joined_at.strftime('%d/%m/%Y') if member.joined_at else 'N/A'}",
        f"🏷️ Roles: {len(member.roles) - 1}",
    ]
    return "\n".join(lines)
