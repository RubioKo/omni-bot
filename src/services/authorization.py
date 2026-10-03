import discord

from .permissions import permission_manager


NATIVE_PERMISSIONS = {
    "mute_user": "moderate_members", "unmute_user": "moderate_members",
    "kick_user": "kick_members", "ban_user": "ban_members",
    "clear_messages": "manage_messages", "set_slowmode": "manage_channels",
    "lockdown": "manage_channels",
}


def authorize_action(actor, guild, action, *, target=None, channel=None):
    if guild is None or actor is None or actor.guild.id != guild.id:
        return "Esta acción requiere un miembro del servidor."
    if not permission_manager.has_permission(actor, action):
        return "Ya no tienes permisos para esta acción."
    native = NATIVE_PERMISSIONS.get(action)
    actor_perms = channel.permissions_for(actor) if channel else actor.guild_permissions
    bot_perms = channel.permissions_for(guild.me) if channel else guild.me.guild_permissions
    if channel and (channel.guild.id != guild.id or not actor_perms.view_channel):
        return "No tienes acceso al canal seleccionado."
    if native and (not getattr(actor_perms, native) or not getattr(bot_perms, native)):
        return "Tú y el bot necesitan los permisos de Discord para esta acción."
    if target:
        if target.guild.id != guild.id or target.id in (guild.owner_id, actor.id, guild.me.id):
            return "No puedes sancionar a ese miembro."
        if actor.id != guild.owner_id and target.top_role >= actor.top_role:
            return "No puedes sancionar a un miembro con rol igual o superior al tuyo."
        if target.top_role >= guild.me.top_role:
            return "No puedo sancionar a un miembro con rol igual o superior al mío."
        if action == "mute_user" and (target.bot or target.guild_permissions.administrator):
            return "No se puede silenciar a bots o administradores."
    return ""


def resolve_text_channel(guild, value, current):
    if not value:
        return current if isinstance(current, discord.TextChannel) else None
    raw = str(value).strip().removeprefix("<#").removesuffix(">")
    if raw.isdigit():
        channel = guild.get_channel(int(raw))
        return channel if isinstance(channel, discord.TextChannel) else None
    matches = [c for c in guild.text_channels if c.name.casefold() == raw.removeprefix("#").casefold()]
    return matches[0] if len(matches) == 1 else None
