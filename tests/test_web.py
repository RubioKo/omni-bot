import sys
from unittest.mock import MagicMock

import pytest
from httpx import ASGITransport, AsyncClient

from src.web import app as web_app


@pytest.fixture()
def fake_bot_module(monkeypatch):
    fake = MagicMock()
    fake.bot.is_ready.return_value = False
    fake.bot._lavalink_ready = False
    monkeypatch.setitem(sys.modules, "src.bot", fake)
    return fake.bot


def _client():
    return AsyncClient(transport=ASGITransport(app=web_app.app), base_url="http://test")


@pytest.mark.asyncio
async def test_health_public():
    async with _client() as ac:
        resp = await ac.get("/health")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"


@pytest.mark.asyncio
async def test_status_404_without_token(monkeypatch):
    monkeypatch.setattr(web_app, "_STATUS_API_TOKEN", "")
    async with _client() as ac:
        resp = await ac.get("/api/status")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_status_404_wrong_token(monkeypatch):
    monkeypatch.setattr(web_app, "_STATUS_API_TOKEN", "test-token")
    async with _client() as ac:
        resp_no_header = await ac.get("/api/status")
        resp_bad = await ac.get("/api/status", headers={"x-api-token": "wrong"})
    assert resp_no_header.status_code == 404
    assert resp_bad.status_code == 404


@pytest.mark.asyncio
async def test_status_ok_with_token(monkeypatch, fake_bot_module):
    monkeypatch.setattr(web_app, "_STATUS_API_TOKEN", "test-token")
    async with _client() as ac:
        resp = await ac.get("/api/status", headers={"x-api-token": "test-token"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ok"
    assert "uptime_seconds" in data
    assert data["user"] == "starting"
