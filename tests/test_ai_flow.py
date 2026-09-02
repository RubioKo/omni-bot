import asyncio
import time

from src.cogs.assistant import AssistantCog, build_confirmation_text, validate_tool_params
from src.services.brain import Brain, MAX_TOOLS_PER_MESSAGE


def make_cog():
    return AssistantCog(bot=None)


def test_build_confirmation_text_single():
    tools = [{"tool": "mute_user", "params": {"user": "@x", "duration": "10m", "reason": "spam"}}]
    text = build_confirmation_text(tools)
    assert "1. 🔇 Silenciar a @x por 10m — spam" in text
    assert "¿Confirmás?" in text


def test_build_confirmation_text_multiple():
    tools = [
        {"tool": "mute_user", "params": {"user": "@x", "duration": "10m"}},
        {"tool": "warn_user", "params": {"user": "@y", "reason": "insultos"}},
    ]
    text = build_confirmation_text(tools)
    assert "1. 🔇 Silenciar a @x por 10m" in text
    assert "2. ⚠️ Advertir a @y — insultos" in text


def test_validate_tool_params_known_tools():
    ok, _ = validate_tool_params("get_server_stats", {})
    assert ok is True
    ok, err = validate_tool_params("warn_user", {"user": "@x", "reason": "spam"})
    assert ok is True
    ok, err = validate_tool_params("warn_user", {})
    assert ok is False
    assert "user" in err


def test_memory_remember_and_get():
    cog = make_cog()
    cog._remember(42, "user", "hola")
    history = cog._get_history(42)
    assert len(history) == 1
    assert history[0] == {"role": "user", "content": "hola"}


def test_memory_truncates_long_content():
    cog = make_cog()
    cog._remember(42, "assistant", "x" * 500)
    history = cog._get_history(42)
    assert len(history[0]["content"]) == 200


def test_memory_max_entries():
    cog = make_cog()
    for i in range(10):
        cog._remember(42, "user", f"msg {i}")
    history = cog._get_history(42)
    assert len(history) == 5
    assert history[-1]["content"] == "msg 9"


def test_memory_expired_entries_pruned(monkeypatch):
    cog = make_cog()
    real_time = time.time
    monkeypatch.setattr(time, "time", lambda: real_time() - 3600)
    cog._remember(42, "user", "viejo")
    monkeypatch.setattr(time, "time", real_time)
    history = cog._get_history(42)
    assert history == []


def test_brain_parse_multiple_tool_calls(monkeypatch):
    class FakeMessage:
        content = ""
        tool_calls = [
            type("TC", (), {"function": type("F", (), {"name": "mute_user", "arguments": '{"user": "x", "duration": "10m"}'})()})(),
            type("TC", (), {"function": type("F", (), {"name": "warn_user", "arguments": '{"user": "y", "reason": "spam"}'})()})(),
        ]

    class FakeChoice:
        finish_reason = "tool_calls"
        message = FakeMessage()

    class FakeResponse:
        choices = [FakeChoice()]

    class FakeCompletions:
        async def create(self, **kwargs):
            return FakeResponse()

    class FakeChat:
        completions = FakeCompletions()

    class FakeClient:
        chat = FakeChat()

    brain = Brain()
    brain.client = FakeClient()

    result = asyncio.run(brain.understand("haz ambas cosas"))
    assert len(result["tools"]) == 2
    assert result["tools"][0]["tool"] == "mute_user"
    assert result["tools"][1]["tool"] == "warn_user"


def test_brain_respects_max_tools(monkeypatch):
    class FakeMessage:
        content = ""
        tool_calls = [
            type("TC", (), {"function": type("F", (), {"name": f"t{i}", "arguments": '{"a": 1}'})()})()
            for i in range(6)
        ]

    class FakeChoice:
        finish_reason = "tool_calls"
        message = FakeMessage()

    class FakeResponse:
        choices = [FakeChoice()]

    class FakeCompletions:
        async def create(self, **kwargs):
            return FakeResponse()

    class FakeChat:
        completions = FakeCompletions()

    class FakeClient:
        chat = FakeChat()

    brain = Brain()
    brain.client = FakeClient()

    result = asyncio.run(brain.understand("muchas cosas"))
    assert len(result["tools"]) == MAX_TOOLS_PER_MESSAGE
