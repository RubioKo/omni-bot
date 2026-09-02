from __future__ import annotations

import asyncio
import datetime
import glob
import logging
import os
import time
from typing import Any

import aiosqlite
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger("OmniBot.database")

DB_DIR = os.getenv(
    "OMNIBOT_DB_DIR",
    os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "data"),
)
DB_PATH = os.path.join(DB_DIR, "omnibot.db")

_db: aiosqlite.Connection | None = None
_write_lock: asyncio.Lock | None = None


async def _get_db() -> aiosqlite.Connection:
    if _db is None:
        raise RuntimeError("Database not initialized. Call init_db() first.")
    return _db


def _get_write_lock() -> asyncio.Lock:
    global _write_lock
    if _write_lock is None:
        _write_lock = asyncio.Lock()
    return _write_lock


async def init_db():
    global _db
    if _db is not None:
        await _db.close()
    os.makedirs(DB_DIR, exist_ok=True)
    _db = await aiosqlite.connect(DB_PATH)
    _db.row_factory = aiosqlite.Row
    await _db.execute("PRAGMA journal_mode=WAL")
    await _db.execute("PRAGMA foreign_keys=ON")
    await _db.execute("PRAGMA busy_timeout=5000")

    await _db.executescript("""
        CREATE TABLE IF NOT EXISTS levels (
            user_id INTEGER PRIMARY KEY,
            xp INTEGER DEFAULT 0,
            level INTEGER DEFAULT 1,
            last_xp_time REAL DEFAULT 0,
            last_voice_time REAL DEFAULT 0
        );
        CREATE TABLE IF NOT EXISTS warnings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            moderator_id INTEGER NOT NULL,
            reason TEXT DEFAULT 'Sin razon',
            active INTEGER DEFAULT 1,
            created_at REAL NOT NULL,
            expires_at REAL NOT NULL
        );
        CREATE TABLE IF NOT EXISTS modlog (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            action TEXT NOT NULL,
            moderator_id INTEGER,
            reason TEXT DEFAULT '',
            created_at REAL NOT NULL
        );
        CREATE TABLE IF NOT EXISTS spam_tracker (
            user_id INTEGER NOT NULL,
            channel_id INTEGER NOT NULL,
            message_count INTEGER DEFAULT 1,
            window_start REAL NOT NULL,
            PRIMARY KEY (user_id, channel_id)
        );
        CREATE TABLE IF NOT EXISTS giveaways (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            guild_id INTEGER NOT NULL,
            channel_id INTEGER NOT NULL,
            message_id INTEGER DEFAULT 0,
            prize TEXT NOT NULL,
            winners INTEGER DEFAULT 1,
            ends_at REAL NOT NULL,
            created_by INTEGER NOT NULL,
            active INTEGER DEFAULT 1
        );
        CREATE TABLE IF NOT EXISTS reminders (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            channel_id INTEGER NOT NULL,
            message TEXT NOT NULL,
            remind_at REAL NOT NULL,
            created_at REAL NOT NULL
        );
        CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS meme_history (
            url TEXT PRIMARY KEY,
            title TEXT DEFAULT '',
            posted_at REAL NOT NULL
        );
        CREATE TABLE IF NOT EXISTS tickets (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            channel_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            subject TEXT NOT NULL,
            status TEXT DEFAULT 'open',
            claimed_by INTEGER,
            created_at REAL NOT NULL,
            closed_at REAL
        );
        CREATE TABLE IF NOT EXISTS meme_feedback (
            url TEXT PRIMARY KEY,
            source TEXT NOT NULL,
            reactions INTEGER DEFAULT 0,
            updated_at REAL NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_warnings_user_active ON warnings(user_id, active, expires_at);
        CREATE INDEX IF NOT EXISTS idx_levels_xp ON levels(xp DESC);
        CREATE INDEX IF NOT EXISTS idx_spam_tracker_window ON spam_tracker(user_id, channel_id, window_start);
        CREATE INDEX IF NOT EXISTS idx_modlog_created ON modlog(created_at DESC);
        CREATE INDEX IF NOT EXISTS idx_giveaways_active ON giveaways(active, ends_at);
        CREATE INDEX IF NOT EXISTS idx_reminders_due ON reminders(remind_at);
        CREATE INDEX IF NOT EXISTS idx_meme_history_posted ON meme_history(posted_at);
        CREATE INDEX IF NOT EXISTS idx_tickets_status ON tickets(status);
        CREATE INDEX IF NOT EXISTS idx_tickets_user_status ON tickets(user_id, status);
        CREATE INDEX IF NOT EXISTS idx_meme_feedback_source ON meme_feedback(source);
    """)
    await _db.commit()
    logger.info("Database initialized")


async def close_db():
    global _db
    if _db is not None:
        await _db.close()
        _db = None
        logger.info("Database closed")


def _xp_for_level(level: int) -> int:
    return level * level * 100


async def add_xp(user_id: int, amount: int) -> dict[str, Any]:
    async with _get_write_lock():
        db = await _get_db()
        now = time.time()
        row = await db.execute_fetchall("SELECT * FROM levels WHERE user_id = ?", (user_id,))
        row = row[0] if row else None

        if row:
            last_time = row["last_xp_time"]
            if now - last_time < 60:
                return {"gained": False, "reason": "cooldown"}

            new_xp = row["xp"] + amount
            new_level = row["level"]
            leveled_up = False

            while new_xp >= _xp_for_level(new_level + 1):
                new_xp -= _xp_for_level(new_level + 1)
                new_level += 1
                leveled_up = True

            await db.execute(
                "UPDATE levels SET xp = ?, level = ?, last_xp_time = ? WHERE user_id = ?",
                (new_xp, new_level, now, user_id),
            )
        else:
            new_xp = amount
            new_level = 1
            leveled_up = False

            while new_xp >= _xp_for_level(new_level + 1):
                new_xp -= _xp_for_level(new_level + 1)
                new_level += 1
                leveled_up = True

            await db.execute(
                "INSERT INTO levels (user_id, xp, level, last_xp_time) VALUES (?, ?, ?, ?)",
                (user_id, new_xp, new_level, now),
            )

        await db.commit()
        return {"gained": True, "xp": new_xp, "level": new_level, "leveled_up": leveled_up, "amount": amount}


async def add_voice_xp(user_id: int, amount: int) -> dict[str, Any]:
    async with _get_write_lock():
        db = await _get_db()
        now = time.time()
        row = await db.execute_fetchall("SELECT * FROM levels WHERE user_id = ?", (user_id,))
        row = row[0] if row else None

        if row:
            last_voice = row["last_voice_time"] or 0
            if now - last_voice < 60:
                return {"gained": False, "reason": "cooldown"}
            new_xp = row["xp"] + amount
            new_level = row["level"]
            leveled_up = False

            while new_xp >= _xp_for_level(new_level + 1):
                new_xp -= _xp_for_level(new_level + 1)
                new_level += 1
                leveled_up = True

            await db.execute(
                "UPDATE levels SET xp = ?, level = ?, last_voice_time = ? WHERE user_id = ?",
                (new_xp, new_level, now, user_id),
            )
        else:
            new_xp = amount
            new_level = 1
            leveled_up = False

            await db.execute(
                "INSERT INTO levels (user_id, xp, level, last_voice_time) VALUES (?, ?, ?, ?)",
                (user_id, new_xp, new_level, now),
            )

        await db.commit()
        return {"gained": True, "xp": new_xp, "level": new_level, "leveled_up": leveled_up}


async def get_level(user_id: int) -> dict[str, int]:
    db = await _get_db()
    rows = await db.execute_fetchall("SELECT * FROM levels WHERE user_id = ?", (user_id,))
    row = rows[0] if rows else None
    if row:
        return {"user_id": user_id, "xp": row["xp"], "level": row["level"]}
    return {"user_id": user_id, "xp": 0, "level": 1}


async def get_leaderboard(limit: int = 10) -> list[dict[str, Any]]:
    db = await _get_db()
    rows = await db.execute_fetchall(
        "SELECT user_id, xp, level FROM levels ORDER BY level DESC, xp DESC LIMIT ?",
        (limit,),
    )
    return [dict(r) for r in rows]


async def get_user_rank_position(user_id: int) -> int:
    db = await _get_db()
    rows = await db.execute_fetchall("SELECT xp FROM levels WHERE user_id = ?", (user_id,))
    row = rows[0] if rows else None
    if not row:
        total_rows = await db.execute_fetchall("SELECT COUNT(*) as cnt FROM levels")
        return total_rows[0]["cnt"] + 1
    pos_rows = await db.execute_fetchall(
        "SELECT COUNT(*) as cnt FROM levels WHERE xp > ?", (row["xp"],)
    )
    return pos_rows[0]["cnt"] + 1


async def add_warning(user_id: int, moderator_id: int, reason: str) -> dict[str, Any]:
    db = await _get_db()
    now = time.time()
    expires = now + 86400

    await db.execute(
        "INSERT INTO warnings (user_id, moderator_id, reason, created_at, expires_at) VALUES (?, ?, ?, ?, ?)",
        (user_id, moderator_id, reason, now, expires),
    )
    await db.commit()

    active_rows = await db.execute_fetchall(
        "SELECT COUNT(*) as cnt FROM warnings WHERE user_id = ? AND active = 1 AND expires_at > ?",
        (user_id, now),
    )
    return {"total_active": active_rows[0]["cnt"], "reason": reason}


async def get_active_warnings(user_id: int) -> list[dict[str, Any]]:
    db = await _get_db()
    now = time.time()
    rows = await db.execute_fetchall(
        "SELECT * FROM warnings WHERE user_id = ? AND active = 1 AND expires_at > ? ORDER BY created_at DESC",
        (user_id, now),
    )
    return [dict(r) for r in rows]


async def clear_warnings(user_id: int) -> int:
    db = await _get_db()
    cursor = await db.execute(
        "UPDATE warnings SET active = 0 WHERE user_id = ? AND active = 1", (user_id,)
    )
    await db.commit()
    return cursor.rowcount


async def log_mod_action(user_id: int, action: str, moderator_id: int, reason: str = ""):
    db = await _get_db()
    await db.execute(
        "INSERT INTO modlog (user_id, action, moderator_id, reason, created_at) VALUES (?, ?, ?, ?, ?)",
        (user_id, action, moderator_id, reason, time.time()),
    )
    await db.commit()


async def get_modlog(limit: int = 20) -> list[dict[str, Any]]:
    db = await _get_db()
    rows = await db.execute_fetchall(
        "SELECT * FROM modlog ORDER BY created_at DESC LIMIT ?", (limit,)
    )
    return [dict(r) for r in rows]


async def create_giveaway(
    guild_id: int, channel_id: int, prize: str, winners: int, ends_at: float, created_by: int
) -> int:
    db = await _get_db()
    cursor = await db.execute(
        "INSERT INTO giveaways (guild_id, channel_id, prize, winners, ends_at, created_by) VALUES (?, ?, ?, ?, ?, ?)",
        (guild_id, channel_id, prize, winners, ends_at, created_by),
    )
    await db.commit()
    return cursor.lastrowid


async def update_giveaway_message(giveaway_id: int, message_id: int):
    db = await _get_db()
    await db.execute("UPDATE giveaways SET message_id = ? WHERE id = ?", (message_id, giveaway_id))
    await db.commit()


async def get_active_giveaways() -> list[dict[str, Any]]:
    db = await _get_db()
    now = time.time()
    rows = await db.execute_fetchall(
        "SELECT * FROM giveaways WHERE active = 1 AND ends_at <= ?", (now,)
    )
    return [dict(r) for r in rows]


async def get_giveaway(giveaway_id: int) -> dict | None:
    db = await _get_db()
    rows = await db.execute_fetchall("SELECT * FROM giveaways WHERE id = ?", (giveaway_id,))
    return dict(rows[0]) if rows else None


async def end_giveaway(giveaway_id: int):
    db = await _get_db()
    await db.execute("UPDATE giveaways SET active = 0 WHERE id = ?", (giveaway_id,))
    await db.commit()


async def create_reminder(user_id: int, channel_id: int, message: str, remind_at: float) -> int:
    db = await _get_db()
    cursor = await db.execute(
        "INSERT INTO reminders (user_id, channel_id, message, remind_at, created_at) VALUES (?, ?, ?, ?, ?)",
        (user_id, channel_id, message, remind_at, time.time()),
    )
    await db.commit()
    return cursor.lastrowid


async def get_due_reminders() -> list[dict[str, Any]]:
    db = await _get_db()
    now = time.time()
    rows = await db.execute_fetchall("SELECT * FROM reminders WHERE remind_at <= ?", (now,))
    return [dict(r) for r in rows]


async def delete_reminder(reminder_id: int):
    db = await _get_db()
    await db.execute("DELETE FROM reminders WHERE id = ?", (reminder_id,))
    await db.commit()


async def track_spam(user_id: int, channel_id: int, window: float = 10.0) -> int:
    db = await _get_db()
    async with _get_write_lock():
        try:
            now = time.time()

            await db.execute(
                "DELETE FROM spam_tracker WHERE user_id = ? AND channel_id = ? AND window_start < ?",
                (user_id, channel_id, now - window),
            )

            rows = await db.execute_fetchall(
                "SELECT * FROM spam_tracker WHERE user_id = ? AND channel_id = ?",
                (user_id, channel_id),
            )
            row = rows[0] if rows else None

            if row:
                new_count = row["message_count"] + 1
                await db.execute(
                    "UPDATE spam_tracker SET message_count = ?, window_start = ? WHERE user_id = ? AND channel_id = ?",
                    (new_count, now, user_id, channel_id),
                )
            else:
                new_count = 1
                await db.execute(
                    "INSERT INTO spam_tracker (user_id, channel_id, message_count, window_start) VALUES (?, ?, ?, ?)",
                    (user_id, channel_id, 1, now),
                )

            await db.commit()
            return new_count
        except Exception:
            await db.rollback()
            logger.error("track_spam finalizó con error; se propaga al automod", exc_info=True)
            raise


async def get_setting(key: str) -> str | None:
    db = await _get_db()
    rows = await db.execute_fetchall("SELECT value FROM settings WHERE key = ?", (key,))
    return rows[0]["value"] if rows else None


async def set_setting(key: str, value: str):
    db = await _get_db()
    await db.execute(
        "INSERT INTO settings (key, value) VALUES (?, ?) "
        "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        (key, value),
    )
    await db.commit()


async def is_meme_seen(url: str) -> bool:
    db = await _get_db()
    rows = await db.execute_fetchall("SELECT 1 FROM meme_history WHERE url = ?", (url,))
    return len(rows) > 0


async def add_meme_history(url: str, title: str):
    db = await _get_db()
    await db.execute(
        "INSERT OR IGNORE INTO meme_history (url, title, posted_at) VALUES (?, ?, ?)",
        (url, title[:200], time.time()),
    )
    await db.commit()


async def prune_meme_history(days: float = 30):
    db = await _get_db()
    cutoff = time.time() - days * 86400
    await db.execute("DELETE FROM meme_history WHERE posted_at < ?", (cutoff,))
    await db.commit()


async def create_ticket(channel_id: int, user_id: int, subject: str) -> int:
    db = await _get_db()
    cursor = await db.execute(
        "INSERT INTO tickets (channel_id, user_id, subject, created_at) VALUES (?, ?, ?, ?)",
        (channel_id, user_id, subject, time.time()),
    )
    await db.commit()
    return cursor.lastrowid


async def get_ticket_by_channel(channel_id: int) -> dict | None:
    db = await _get_db()
    rows = await db.execute_fetchall(
        "SELECT * FROM tickets WHERE channel_id = ? AND status = 'open'", (channel_id,)
    )
    return dict(rows[0]) if rows else None


async def get_open_ticket_count(user_id: int) -> int:
    db = await _get_db()
    rows = await db.execute_fetchall(
        "SELECT COUNT(*) as cnt FROM tickets WHERE user_id = ? AND status = 'open'", (user_id,)
    )
    return rows[0]["cnt"]


async def claim_ticket(ticket_id: int, staff_id: int):
    db = await _get_db()
    await db.execute("UPDATE tickets SET claimed_by = ? WHERE id = ?", (staff_id, ticket_id))
    await db.commit()


async def close_ticket(ticket_id: int):
    db = await _get_db()
    await db.execute(
        "UPDATE tickets SET status = 'closed', closed_at = ? WHERE id = ?",
        (time.time(), ticket_id),
    )
    await db.commit()


async def record_meme_feedback(url: str, source: str, delta: int):
    db = await _get_db()
    await db.execute(
        "INSERT INTO meme_feedback (url, source, reactions, updated_at) VALUES (?, ?, ?, ?) "
        "ON CONFLICT(url) DO UPDATE SET reactions = MAX(0, meme_feedback.reactions + ?), "
        "updated_at = excluded.updated_at",
        (url, source, max(delta, 0), time.time(), delta),
    )
    await db.commit()


async def get_source_weights(days: float = 14) -> dict[str, float]:
    db = await _get_db()
    cutoff = time.time() - days * 86400
    rows = await db.execute_fetchall(
        "SELECT source, SUM(reactions) as total, COUNT(*) as cnt "
        "FROM meme_feedback WHERE reactions > 0 AND updated_at > ? "
        "GROUP BY source",
        (cutoff,),
    )
    return {r["source"]: r["total"] / r["cnt"] for r in rows if r["cnt"] > 0}


async def get_weekly_winner(days: float = 7) -> dict[str, Any] | None:
    db = await _get_db()
    cutoff = time.time() - days * 86400
    rows = await db.execute_fetchall(
        "SELECT url, source, reactions FROM meme_feedback "
        "WHERE reactions > 0 AND updated_at > ? "
        "ORDER BY reactions DESC LIMIT 1",
        (cutoff,),
    )
    if not rows:
        return None
    row = rows[0]
    hist_rows = await db.execute_fetchall(
        "SELECT title, posted_at FROM meme_history WHERE url = ?", (row["url"],)
    )
    hist = hist_rows[0] if hist_rows else None
    return {
        "url": row["url"],
        "source": row["source"],
        "reactions": row["reactions"],
        "title": hist["title"] if hist else "",
        "posted_at": hist["posted_at"] if hist else 0,
    }


async def backup_database() -> str | None:
    os.makedirs(DB_DIR, exist_ok=True)
    backup_dir = os.path.join(DB_DIR, "backups")
    os.makedirs(backup_dir, exist_ok=True)

    if not os.path.exists(DB_PATH):
        logger.warning("Backup skipped: database file does not exist")
        return None

    stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    backup_path = os.path.join(backup_dir, f"omnibot-{stamp}.db")

    try:
        src = await aiosqlite.connect(DB_PATH)
        try:
            dst = await aiosqlite.connect(backup_path)
            try:
                await src.backup(dst)
            finally:
                await dst.close()
        finally:
            await src.close()
    except Exception as e:
        logger.error(f"Database backup failed: {e}")
        return None

    return backup_path


async def prune_backups(retention_days: int = 7) -> int:
    backup_dir = os.path.join(DB_DIR, "backups")
    if not os.path.isdir(backup_dir):
        return 0

    cutoff = time.time() - retention_days * 86400
    removed = 0
    for path in glob.glob(os.path.join(backup_dir, "omnibot-*.db")):
        try:
            mtime = os.path.getmtime(path)
            if mtime < cutoff:
                os.remove(path)
                removed += 1
        except OSError as e:
            logger.warning(f"Failed to remove backup {path}: {e}")
    return removed
