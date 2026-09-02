import pytest

from src.cogs.tickets import _sanitize_channel_name


@pytest.mark.asyncio
async def test_create_and_get_ticket(db):
    tid = await db.create_ticket(1001, 5001, "no puedo entrar")
    assert tid > 0

    ticket = await db.get_ticket_by_channel(1001)
    assert ticket is not None
    assert ticket["subject"] == "no puedo entrar"
    assert ticket["user_id"] == 5001
    assert ticket["status"] == "open"


@pytest.mark.asyncio
async def test_get_ticket_nonexistent(db):
    assert await db.get_ticket_by_channel(9999) is None


@pytest.mark.asyncio
async def test_open_ticket_count(db):
    assert await db.get_open_ticket_count(7001) == 0
    await db.create_ticket(2001, 7001, "asunto 1")
    assert await db.get_open_ticket_count(7001) == 1
    await db.create_ticket(2002, 7001, "asunto 2")
    assert await db.get_open_ticket_count(7001) == 2


@pytest.mark.asyncio
async def test_close_ticket(db):
    tid = await db.create_ticket(3001, 8001, "cerrar test")
    await db.close_ticket(tid)

    assert await db.get_ticket_by_channel(3001) is None
    assert await db.get_open_ticket_count(8001) == 0


@pytest.mark.asyncio
async def test_claim_ticket(db):
    tid = await db.create_ticket(4001, 9001, "claim test")
    await db.claim_ticket(tid, 12345)

    import sqlite3
    conn = sqlite3.connect(db.DB_PATH)
    try:
        row = conn.execute(
            "SELECT claimed_by FROM tickets WHERE id = ?", (tid,)
        ).fetchone()
    finally:
        conn.close()
    assert row[0] == 12345


def test_sanitize_channel_name():
    assert _sanitize_channel_name("Jhon_K García") == "jhonkgarca"
    assert _sanitize_channel_name("$$$") == "usuario"
    assert _sanitize_channel_name("un-nombre-muy-muy-muy-largo-de-usuario") == "un-nombre-muy-muy-muy-lar"
