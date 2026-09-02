from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from dotenv import load_dotenv

if TYPE_CHECKING:
    from discord import Member

load_dotenv()

_SECRET_KEYS = frozenset({
    "discord_token", "openrouter_api_key",
    "lavalink_password", "reddit_client_secret",
})


class SecretStr(str):
    def __repr__(self) -> str:
        s = str(self)
        if len(s) <= 8:
            return "***"
        return s[:4] + "***" + s[-4:]


def _env_int(key: str, default: int = 0) -> int:
    raw = os.getenv(key, "").strip()
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError:
        logger = logging.getLogger("OmniBot.config")
        logger.warning(f"Env var {key} has non-numeric value '{raw}', using default {default}")
        return default


def _env_secret(key: str, default: str = "") -> SecretStr:
    return SecretStr(os.getenv(key, default).strip())


@dataclass
class Config:
    discord_token: str = field(default_factory=lambda: _env_secret("DISCORD_TOKEN"))
    openrouter_api_key: str = field(default_factory=lambda: _env_secret("OPENROUTER_API_KEY"))
    openrouter_model: str = field(default_factory=lambda: os.getenv("OPENROUTER_MODEL", "openai/gpt-4o-mini"))
    meme_timezone: str = field(default_factory=lambda: os.getenv("MEME_TIMEZONE", "America/Argentina/Buenos_Aires").strip())
    lavalink_uri: str = field(default_factory=lambda: os.getenv("LAVALINK_URI", "http://127.0.0.1:2333").strip())
    lavalink_password: str = field(default_factory=lambda: _env_secret("LAVALINK_PASSWORD", "changeme"))
    autoradio_channel_id: int = field(default_factory=lambda: _env_int("AUTORADIO_CHANNEL_ID"))
    autoradio_station: str = field(default_factory=lambda: os.getenv("AUTORADIO_STATION", "rock"))
    meme_subreddits: str = field(default_factory=lambda: os.getenv(
        "MEME_SUBREDDITS",
        "memes,dankmemes,me_irl,gaming",
    ).strip())
    meme_hours: str = field(default_factory=lambda: os.getenv("MEME_HOURS", "10,18").strip())
    meme_theme_days: str = field(default_factory=lambda: os.getenv(
        "MEME_THEME_DAYS", "0:gaming,2:dark,4:futbol"
    ).strip())
    reddit_client_id: str = field(default_factory=lambda: os.getenv("REDDIT_CLIENT_ID", "").strip())
    reddit_client_secret: str = field(default_factory=lambda: _env_secret("REDDIT_CLIENT_SECRET"))
    banned_words: str = field(default_factory=lambda: os.getenv("BANNED_WORDS", "").strip())
    raid_auto_lockdown: bool = field(default_factory=lambda: os.getenv("RAID_AUTO_LOCKDOWN", "1").strip() == "1")
    min_account_age_days: int = field(default_factory=lambda: _env_int("MIN_ACCOUNT_AGE_DAYS", 7))
    backup_retention_days: int = field(default_factory=lambda: _env_int("BACKUP_RETENTION_DAYS", 7))
    health_check_port: int = field(default_factory=lambda: _env_int("HEALTH_CHECK_PORT", 8080))

    def __repr__(self) -> str:
        parts = []
        for f_name in self.__dataclass_fields__:
            val = getattr(self, f_name)
            if f_name in _SECRET_KEYS:
                parts.append(f"  {f_name}={SecretStr(val)!r}")
            else:
                parts.append(f"  {f_name}={val!r}")
        return "Config(\n" + "\n".join(parts) + "\n)"

    @property
    def has_ai(self) -> bool:
        return bool(self.openrouter_api_key)

    @property
    def is_ready(self) -> bool:
        return bool(self.discord_token)


STAFF_ROLE_NAMES: list[str] = ["MODERADOR", "STAFF", "ADMINISTRADOR", "G/M", "PROPIETARIO", "🛡️ Staff Helper"]
_STAFF_NAMES_UPPER = frozenset(n.upper() for n in STAFF_ROLE_NAMES)


def is_staff(member: Member) -> bool:
    return any(r.name.upper() in _STAFF_NAMES_UPPER for r in member.roles)


config = Config()

if config.lavalink_password == "changeme":
    logging.getLogger("OmniBot.config").warning(
        "LAVALINK_PASSWORD usa el valor por defecto. "
        "Define una contraseña fuerte en las variables de entorno de Dokploy."
    )
