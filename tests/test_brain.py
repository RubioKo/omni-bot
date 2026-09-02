from src.services.brain import Brain


def make_basic_brain():
    brain = Brain()
    brain.client = None
    return brain


def first_tool(result):
    return result["tools"][0]["tool"]


def test_basic_match_warn():
    brain = make_basic_brain()
    result = brain._basic_match("advertir al usuario que spamea")
    assert first_tool(result) == "warn_user"
    assert "reason" in result["tools"][0]["params"]


def test_basic_match_mute():
    brain = make_basic_brain()
    result = brain._basic_match("silenciar a pepe 10 minutos")
    assert first_tool(result) == "mute_user"
    assert result["tools"][0]["params"]["duration"] == "10m"


def test_basic_match_stats():
    brain = make_basic_brain()
    result = brain._basic_match("dame las estadisticas del server")
    assert first_tool(result) == "get_server_stats"


def test_basic_match_no_false_positive_adv():
    brain = make_basic_brain()
    result = brain._basic_match("alguien vio el adverbio ese")
    assert result.get("tools") == []


def test_basic_match_no_false_positive_server_chat():
    brain = make_basic_brain()
    result = brain._basic_match("como va todo")
    assert result.get("tools") == []


def test_basic_match_unknown():
    brain = make_basic_brain()
    result = brain._basic_match("blablabla nada que ver")
    assert result["text"]
    assert result.get("tools") == []


def test_extract_user_mention():
    brain = make_basic_brain()
    assert brain._extract_user("advertir <@123456789> por spam") == "<@123456789>"
    assert brain._extract_user("advertir <@!987654321> por spam") == "<@!987654321>"


def test_extract_user_fallback():
    brain = make_basic_brain()
    assert brain._extract_user("advertir a pepe") == "usuario"


def test_build_messages_with_history_and_level():
    brain = make_basic_brain()
    history = [
        {"role": "user", "content": "quien es pepe"},
        {"role": "assistant", "content": "pepe es un miembro"},
    ]
    messages = brain._build_messages("y silencialo", history, "MODERADOR")
    assert messages[0]["role"] == "system"
    assert "MODERADOR" in messages[0]["content"]
    assert len(messages) == 4
    assert messages[1] == history[0]
    assert messages[-1] == {"role": "user", "content": "y silencialo"}


def test_compose_response_no_client_joins_results():
    import asyncio
    brain = make_basic_brain()
    result = asyncio.run(
        brain.compose_response(["🔇 @x silenciado", "⚠️ @y advertido"], "hazlo", "ADMINISTRADOR")
    )
    assert "silenciado" in result
    assert "advertido" in result


def test_tool_definitions_exclude_wow_and_7dtd():
    from src.services.brain import TOOL_DEFINITIONS
    names = {td["function"]["name"] for td in TOOL_DEFINITIONS}
    for removed in ("get_build", "get_meta", "get_news", "get_server_status_7dtd", "get_blood_moon"):
        assert removed not in names
    assert "warn_user" in names
    assert "get_server_stats" in names
