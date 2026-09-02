import asyncio
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


@pytest.fixture()
def db(tmp_path, monkeypatch):
    from src.services import database
    monkeypatch.setattr(database, "DB_DIR", str(tmp_path))
    monkeypatch.setattr(database, "DB_PATH", str(tmp_path / "omnibot.db"))
    asyncio.run(database.init_db())
    yield database
    asyncio.run(database.close_db())
    database._write_lock = None
