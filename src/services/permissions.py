import logging
import time
from enum import IntEnum

logger = logging.getLogger("OmniBot.permissions")

class PermissionLevel(IntEnum):
    MEMBER = 0
    DJ = 1
    VIP = 2
    MODERATOR = 3
    ADMIN = 4
    OWNER = 5

ROLE_PERMISSION_MAP = {
    PermissionLevel.MEMBER: ["🔫 VALORANT PLAYER", "🏗️ FORTNITE PLAYER",
        "⚔️ LOL PLAYER", "🎯 ARENA BREAKOUT PLAYER",
        "🌸 GENSHIN PLAYER", "⚔️ HOTS PLAYER", "😎 CASUAL", "🏆 COMPETITIVE",
        "🎬 CREADOR", "👥 LFG"],
    PermissionLevel.DJ: ["DJ"],
    PermissionLevel.VIP: ["🏆 VIP"],
    PermissionLevel.MODERATOR: ["MODERADOR", "STAFF", "🛡️ STAFF HELPER"],
    PermissionLevel.ADMIN: ["ADMINISTRADOR", "G/M"],
    PermissionLevel.OWNER: ["PROPIETARIO", "👑 PROPIETARIO"],
}

COMMAND_PERMISSIONS = {
    "warn_user": PermissionLevel.MODERATOR,
    "mute_user": PermissionLevel.MODERATOR,
    "unmute_user": PermissionLevel.MODERATOR,
    "clear_messages": PermissionLevel.ADMIN,
    "set_slowmode": PermissionLevel.MODERATOR,
    "kick_user": PermissionLevel.MODERATOR,
    "ban_user": PermissionLevel.MODERATOR,
    "get_server_stats": PermissionLevel.MEMBER,
    "get_user_info": PermissionLevel.MEMBER,
    "play_music": PermissionLevel.DJ,
    "skip_music": PermissionLevel.DJ,
    "stop_music": PermissionLevel.DJ,
    "volume_music": PermissionLevel.DJ,
    "loop_music": PermissionLevel.DJ,
    "pause_music": PermissionLevel.DJ,
    "resume_music": PermissionLevel.DJ,
    "disconnect_music": PermissionLevel.DJ,
    "play_radio": PermissionLevel.MEMBER,
    "admin_config": PermissionLevel.ADMIN,
    "lockdown": PermissionLevel.MODERATOR,
    "reglas": PermissionLevel.MODERATOR,
    "clearwarnings": PermissionLevel.MODERATOR,
    "xplb": PermissionLevel.OWNER,
    "ticket_panel": PermissionLevel.ADMIN,
}

RATE_LIMITS = {
    PermissionLevel.MEMBER: 5,
    PermissionLevel.DJ: 10,
    PermissionLevel.VIP: 10,
    PermissionLevel.MODERATOR: 15,
    PermissionLevel.ADMIN: 20,
    PermissionLevel.OWNER: 999,
}

class PermissionManager:
    def __init__(self):
        self.user_cooldowns = {}

    def _prune_cooldowns(self, now: float):
        expired = [uid for uid, (ts, _) in self.user_cooldowns.items() if now - ts > 120]
        for uid in expired:
            del self.user_cooldowns[uid]

    def get_permission_level(self, member) -> PermissionLevel:
        if not member or not hasattr(member, 'roles'):
            return PermissionLevel.MEMBER
        highest = PermissionLevel.MEMBER
        for role in member.roles:
            role_name = role.name.upper()
            for level, role_names in ROLE_PERMISSION_MAP.items():
                if role_name in role_names and level > highest:
                    highest = level
        return highest

    def has_permission(self, member, command: str) -> bool:
        user_level = self.get_permission_level(member)
        required_level = COMMAND_PERMISSIONS.get(command, PermissionLevel.OWNER)
        return user_level >= required_level

    def get_rate_limit(self, member) -> int:
        level = self.get_permission_level(member)
        return RATE_LIMITS.get(level, 5)

    def get_permission_name(self, member) -> str:
        level = self.get_permission_level(member)
        names = {
            PermissionLevel.MEMBER: "MIEMBRO",
            PermissionLevel.DJ: "DJ",
            PermissionLevel.VIP: "VIP",
            PermissionLevel.MODERATOR: "MODERADOR",
            PermissionLevel.ADMIN: "ADMINISTRADOR",
            PermissionLevel.OWNER: "PROPIETARIO",
        }
        return names.get(level, "MIEMBRO")

    def get_required_level_name(self, command: str) -> str:
        required = COMMAND_PERMISSIONS.get(command, PermissionLevel.OWNER)
        names = {
            PermissionLevel.MEMBER: "MIEMBRO",
            PermissionLevel.DJ: "DJ",
            PermissionLevel.VIP: "VIP",
            PermissionLevel.MODERATOR: "MODERADOR",
            PermissionLevel.ADMIN: "ADMINISTRADOR",
            PermissionLevel.OWNER: "PROPIETARIO",
        }
        return names.get(required, "PROPIETARIO")

    def consume_rate_limit(self, member) -> tuple[bool, int]:
        user_id = member.id
        now = time.time()
        self._prune_cooldowns(now)
        if user_id in self.user_cooldowns:
            last_time, count = self.user_cooldowns[user_id]
            if now - last_time < 60:
                limit = self.get_rate_limit(member)
                if count >= limit:
                    wait_time = int(60 - (now - last_time))
                    return False, wait_time
                self.user_cooldowns[user_id] = (last_time, count + 1)
            else:
                self.user_cooldowns[user_id] = (now, 1)
        else:
            self.user_cooldowns[user_id] = (now, 1)
        return True, 0

permission_manager = PermissionManager()
