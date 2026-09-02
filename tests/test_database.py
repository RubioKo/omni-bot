import pytest

from src.services import database


@pytest.mark.asyncio
async def test_init_db_creates_tables(db):
    import sqlite3
    conn = sqlite3.connect(db.DB_PATH)
    try:
        tables = {r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()}
    finally:
        conn.close()
    for expected in ("levels", "warnings", "modlog", "spam_tracker", "giveaways", "reminders", "settings"):
        assert expected in tables


@pytest.mark.asyncio
async def test_add_xp_and_levels(db):
    result = await db.add_xp(1, 25)
    assert result["gained"] is True
    assert result["xp"] == 25
    assert result["level"] == 1

    level = await db.get_level(1)
    assert level["xp"] == 25
    assert level["level"] == 1


@pytest.mark.asyncio
async def test_add_xp_cooldown(db):
    first = await db.add_xp(2, 25)
    second = await db.add_xp(2, 25)
    assert first["gained"] is True
    assert second["gained"] is False
    assert second["reason"] == "cooldown"


@pytest.mark.asyncio
async def test_add_voice_xp(db):
    result = await db.add_voice_xp(3, 20)
    assert result["gained"] is True
    assert result["xp"] == 20


@pytest.mark.asyncio
async def test_leaderboard_and_rank(db):
    await db.add_xp(10, 50)
    await db.add_xp(11, 100)
    top = await db.get_leaderboard(10)
    assert top[0]["user_id"] == 11

    pos = await db.get_user_rank_position(11)
    assert pos == 1
    pos2 = await db.get_user_rank_position(10)
    assert pos2 == 2


@pytest.mark.asyncio
async def test_warnings_lifecycle(db):
    warning = await db.add_warning(20, 99, "spam test")
    assert warning["total_active"] == 1

    active = await db.get_active_warnings(20)
    assert len(active) == 1
    assert active[0]["reason"] == "spam test"

    cleared = await db.clear_warnings(20)
    assert cleared == 1
    assert await db.get_active_warnings(20) == []


@pytest.mark.asyncio
async def test_modlog(db):
    await db.log_mod_action(30, "WARN", 99, "test reason")
    logs = await db.get_modlog(10)
    assert len(logs) == 1
    assert logs[0]["action"] == "WARN"
    assert logs[0]["reason"] == "test reason"


@pytest.mark.asyncio
async def test_settings_roundtrip(db):
    assert await db.get_setting("nonexistent") is None
    await db.set_setting("key1", "value1")
    assert await db.get_setting("key1") == "value1"
    await db.set_setting("key1", "value2")
    assert await db.get_setting("key1") == "value2"


@pytest.mark.asyncio
async def test_giveaway_lifecycle(db):
    import time
    gid = await db.create_giveaway(1, 2, "prize", 1, time.time() + 60, 99)
    assert gid > 0

    await db.update_giveaway_message(gid, 12345)
    gw = await db.get_giveaway(gid)
    assert gw["message_id"] == 12345

    active = await db.get_active_giveaways()
    assert active == []

    await db.end_giveaway(gid)
    gw_after = await db.get_giveaway(gid)
    assert gw_after["active"] == 0


@pytest.mark.asyncio
async def test_giveaway_due_detection(db):
    import time
    gid = await db.create_giveaway(1, 2, "expired", 1, time.time() - 10, 99)
    due = await db.get_active_giveaways()
    assert any(g["id"] == gid for g in due)


@pytest.mark.asyncio
async def test_reminders(db):
    import time
    rid = await db.create_reminder(40, 5, "recordar", time.time() + 30)
    assert rid > 0
    assert await db.get_due_reminders() == []
    await db.delete_reminder(rid)
    assert await db.get_due_reminders() == []


@pytest.mark.asyncio
async def test_track_spam_window(db):
    counts = [await db.track_spam(50, 1, 10.0) for _ in range(5)]
    assert counts == [1, 2, 3, 4, 5]

    counts_other_channel = [await db.track_spam(50, 2, 10.0) for _ in range(2)]
    assert counts_other_channel == [1, 2]


@pytest.mark.asyncio
async def test_track_spam_concurrent_no_lost_update(db):
    import asyncio
    results = await asyncio.gather(
        db.track_spam(60, 1, 10.0),
        db.track_spam(60, 1, 10.0),
    )
    assert sorted(results) == [1, 2]


@pytest.mark.asyncio
async def test_add_xp_concurrent_single_grant(db):
    import asyncio
    results = await asyncio.gather(
        *(db.add_xp(90, 50) for _ in range(3)),
    )
    gained = [r for r in results if r["gained"]]
    assert len(gained) == 1
    level = await db.get_level(90)
    assert level["xp"] == 50


@pytest.mark.asyncio
async def test_add_voice_xp_concurrent_single_grant(db):
    import asyncio
    results = await asyncio.gather(
        *(db.add_voice_xp(91, 20) for _ in range(3)),
    )
    gained = [r for r in results if r["gained"]]
    assert len(gained) == 1
    level = await db.get_level(91)
    assert level["xp"] == 20


@pytest.mark.asyncio
async def test_track_spam_propagates_errors(db, monkeypatch):
    class Boom(Exception):
        pass

    async def _boom(*args, **kwargs):
        raise Boom("db error")

    class _BoomDB:
        execute = _boom
        execute_fetchall = _boom

        async def commit(self):
            pass

        async def rollback(self):
            pass

    async def _fake_get_db():
        return _BoomDB()

    monkeypatch.setattr(database, "_get_db", _fake_get_db)
    with pytest.raises(Boom):
        await database.track_spam(70, 1, 10.0)


@pytest.mark.asyncio
async def test_backup_database_creates_file(db):
    import os
    path = await db.backup_database()
    assert path is not None
    assert os.path.exists(path)
    assert os.path.getsize(path) > 0
    assert "backups" in path


@pytest.mark.asyncio
async def test_backup_database_missing_db_file(db):
    import os
    await db.close_db()
    os.remove(db.DB_PATH)
    assert await db.backup_database() is None
    await db.init_db()


@pytest.mark.asyncio
async def test_prune_backups_retention(db):
    import os
    import time as time_mod

    path = await db.backup_database()
    assert path is not None

    old_time = time_mod.time() - 30 * 86400
    os.utime(path, (old_time, old_time))
    removed = await db.prune_backups(7)
    assert removed >= 1
    assert not os.path.exists(path)


@pytest.mark.asyncio
async def test_prune_backups_keeps_recent(db):
    import os
    path = await db.backup_database()
    removed = await db.prune_backups(7)
    assert removed == 0
    assert os.path.exists(path)


@pytest.mark.asyncio
async def test_backup_database_is_valid_copy(db):
    import sqlite3
    path = await db.backup_database()
    conn = sqlite3.connect(path)
    try:
        tables = {r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()}
    finally:
        conn.close()
    assert "levels" in tables
    assert "tickets" in tables


@pytest.mark.asyncio
async def test_meme_feedback_upsert_and_weights(db):
    await db.record_meme_feedback("url1", "maau", 3)
    await db.record_meme_feedback("url1", "maau", 2)
    await db.record_meme_feedback("url2", "maau", 1)
    await db.record_meme_feedback("url3", "memexico", 5)

    weights = await db.get_source_weights()
    assert weights["maau"] == 3.0
    assert weights["memexico"] == 5.0


@pytest.mark.asyncio
async def test_meme_feedback_removal_floors_at_zero(db):
    await db.record_meme_feedback("urlX", "maau", 1)
    await db.record_meme_feedback("urlX", "maau", -1)
    await db.record_meme_feedback("urlX", "maau", -1)
    weights = await db.get_source_weights()
    assert "maau" not in weights


@pytest.mark.asyncio
async def test_weekly_winner(db):
    await db.record_meme_feedback("win1", "maau", 10)
    await db.record_meme_feedback("lose1", "memexico", 2)
    winner = await db.get_weekly_winner(7)
    assert winner is not None
    assert winner["url"] == "win1"
    assert winner["source"] == "maau"
    assert winner["reactions"] == 10


@pytest.mark.asyncio
async def test_weekly_winner_none_without_feedback(db):
    assert await db.get_weekly_winner(7) is None
