import logging
import logging.config
import os
import sys

LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").strip().upper() or "INFO"

LOGGING_CONFIG = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "default": {
            "format": "%(asctime)s [%(name)s] %(levelname)s: %(message)s",
            "datefmt": "%Y-%m-%d %H:%M:%S",
        },
    },
    "handlers": {
        "console": {
            "class": "logging.StreamHandler",
            "formatter": "default",
            "level": LOG_LEVEL,
        },
    },
    "root": {
        "handlers": ["console"],
        "level": LOG_LEVEL,
    },
    "loggers": {
        "discord.http": {"level": "WARNING"},
        "discord.gateway": {"level": "WARNING"},
        "websockets": {"level": "WARNING"},
        "httpcore": {"level": "WARNING"},
        "httpx": {"level": "WARNING"},
        "openai": {"level": "WARNING"},
        "wavelink": {"level": "WARNING"},
    },
}

if os.getenv("LOG_FILE"):
    LOGGING_CONFIG["handlers"]["file"] = {
        "class": "logging.handlers.RotatingFileHandler",
        "filename": os.environ["LOG_FILE"],
        "maxBytes": 5 * 1024 * 1024,
        "backupCount": 3,
        "formatter": "default",
        "level": LOG_LEVEL,
    }
    LOGGING_CONFIG["root"]["handlers"].append("file")

logging.config.dictConfig(LOGGING_CONFIG)

logger = logging.getLogger("OmniBot")

def main():
    from .bot import bot
    from .config import config

    if not config.is_ready:
        logger.error("DISCORD_TOKEN no configurado. Abortando inicio.")
        sys.exit(1)

    logger.info("Starting OmniBot...")
    bot.run(config.discord_token)

if __name__ == "__main__":
    main()
