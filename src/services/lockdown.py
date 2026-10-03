import json

import discord

from . import database as db
from .permissions import permission_manager, PermissionLevel

FIELDS = ("send_messages", "send_messages_in_threads", "create_public_threads", "create_private_threads")


def _exempt(guild, target):
    if isinstance(target, discord.Member):
        return target.id in (guild.owner_id, guild.me.id) or permission_manager.get_permission_level(target) >= PermissionLevel.MODERATOR
    return target.permissions.administrator or target.id in {r.id for r in permission_manager.staff_roles(guild)}


async def set_lockdown(guild, enabled):
    key = f"lockdown_{guild.id}"
    raw = await db.get_setting(key)
    state = json.loads(raw) if raw else {}
    if enabled:
        if state:
            return
        for channel in [*guild.text_channels, *guild.forums]:
            if channel.name == "mod-logs" or (channel.category and channel.category.name in ("STAFF", "TICKETS")):
                continue
            targets = {guild.default_role, *channel.overwrites.keys()}
            for target in targets:
                if _exempt(guild, target):
                    continue
                overwrite = channel.overwrites_for(target)
                if target != guild.default_role and not any(getattr(overwrite, f) is True for f in FIELDS):
                    continue
                entry_key = f"{channel.id}:{target.id}"
                state[entry_key] = {
                    "channel_id": channel.id, "target_id": target.id,
                    "member": isinstance(target, discord.Member),
                    "values": {f: getattr(overwrite, f) for f in FIELDS},
                }
                await db.set_setting(key, json.dumps(state))
                for field in FIELDS:
                    setattr(overwrite, field, False)
                await channel.set_permissions(target, overwrite=overwrite, reason="OmniBot lockdown")
    else:
        for entry_key, entry in list(state.items()):
            channel = guild.get_channel(entry["channel_id"])
            if entry["member"]:
                target = guild.get_member(entry["target_id"])
                if target is None:
                    try:
                        target = await guild.fetch_member(entry["target_id"])
                    except discord.NotFound:
                        pass
            else:
                target = guild.get_role(entry["target_id"])
            if channel and target:
                overwrite = channel.overwrites_for(target)
                for field, value in entry["values"].items():
                    setattr(overwrite, field, value)
                await channel.set_permissions(target, overwrite=None if overwrite.is_empty() else overwrite, reason="OmniBot unlockdown")
            state.pop(entry_key)
            await db.set_setting(key, json.dumps(state))
        await db.set_setting(key, "")
