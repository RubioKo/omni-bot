import discord
import logging

from .permissions import permission_manager

logger = logging.getLogger("OmniBot.modlog")


async def get_or_create_modlogs(guild: discord.Guild) -> discord.TextChannel | None:
    existing = discord.utils.get(guild.text_channels, name="mod-logs")
    if existing:
        for role in guild.roles:
            if existing.permissions_for(role).view_channel and not role.permissions.administrator and role not in permission_manager.staff_roles(guild):
                logger.error("El canal mod-logs permite acceso a roles no autorizados")
                return None
        for target in existing.overwrites:
            if isinstance(target, discord.Member) and existing.permissions_for(target).view_channel and target.id != guild.me.id:
                from ..config import is_staff
                if not is_staff(target):
                    return None
        return existing

    category = (
        discord.utils.get(guild.categories, name="STAFF")
        or discord.utils.get(guild.categories, name="TICKETS")
    )

    overwrites = {
        guild.default_role: discord.PermissionOverwrite(read_messages=False),
        guild.me: discord.PermissionOverwrite(
            read_messages=True, send_messages=True, read_message_history=True,
        ),
    }
    for role in permission_manager.staff_roles(guild):
        if role:
            overwrites[role] = discord.PermissionOverwrite(
                read_messages=True, send_messages=True, read_message_history=True,
            )

    try:
        channel = await guild.create_text_channel(
            "mod-logs",
            category=category,
            overwrites=overwrites,
            topic="Registros automáticos de moderación y tickets (solo staff)",
        )
        logger.info(f"Created #mod-logs channel in {guild.name}")
        return channel
    except discord.Forbidden:
        logger.warning(f"No permissions to create #mod-logs in {guild.name}")
        return None


async def log_action(
    guild: discord.Guild,
    *,
    action: str,
    target_id: int,
    moderator_id: int,
    reason: str = "",
) -> None:
    channel = await get_or_create_modlogs(guild)
    if channel is None:
        return

    description = f"**Objetivo:** <@{target_id}>\n**Moderador:** <@{moderator_id}>"
    if reason:
        description += f"\n**Razón:** {reason[:500]}"

    embed = discord.Embed(
        title=f"🛡️ {action}",
        description=description,
        color=0xED4245,
        timestamp=discord.utils.utcnow(),
    )
    try:
        await channel.send(embed=embed)
    except discord.Forbidden:
        logger.warning("No permissions to post in #mod-logs")
