import re

import discord


def resolve_member(guild: discord.Guild, user_str: str) -> discord.Member | None:
    """Resuelve un usuario con prioridad: mención > exacto > prefijo > substring."""
    if not guild or not user_str:
        return None

    target = user_str.strip()
    if not target:
        return None

    match = re.fullmatch(r"<@!?(\d+)>", target)
    if match or target.isdigit():
        return guild.get_member(int(match.group(1) if match else target))

    lowered = target.lower()

    exact = [
        m for m in guild.members
        if m.name.lower() == lowered or (m.nick and m.nick.lower() == lowered)
    ]
    if exact:
        return exact[0] if len(exact) == 1 else None

    prefix = [
        m for m in guild.members
        if m.name.lower().startswith(lowered) or (m.nick and m.nick.lower().startswith(lowered))
    ]
    if prefix:
        return prefix[0] if len(prefix) == 1 else None

    matches = [m for m in guild.members if lowered in m.name.lower() or (m.nick and lowered in m.nick.lower())]
    return matches[0] if len(matches) == 1 else None
