import re

import discord


def resolve_member(guild: discord.Guild, user_str: str) -> discord.Member | None:
    """Resuelve un usuario con prioridad: mención > exacto > prefijo > substring."""
    if not guild or not user_str:
        return None

    target = user_str.strip()
    if not target:
        return None

    match = re.search(r"<@!?(\d+)>", target)
    if match:
        member = guild.get_member(int(match.group(1)))
        if member:
            return member

    lowered = target.lower()

    exact = [
        m for m in guild.members
        if m.name.lower() == lowered or (m.nick and m.nick.lower() == lowered)
    ]
    if len(exact) == 1:
        return exact[0]

    prefix = [
        m for m in guild.members
        if m.name.lower().startswith(lowered) or (m.nick and m.nick.lower().startswith(lowered))
    ]
    if len(prefix) == 1:
        return prefix[0]

    for m in guild.members:
        if lowered in m.name.lower() or (m.nick and lowered in m.nick.lower()):
            return m

    return None
