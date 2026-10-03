from src.cogs.assistant import validate_tool_params


def test_valid_params():
    ok, err = validate_tool_params("warn_user", {"user": "@user", "reason": "test"})
    assert ok is True
    assert err == ""


def test_missing_required_field():
    ok, err = validate_tool_params("warn_user", {})
    assert ok is False
    assert "user" in err


def test_unknown_tool_rejected():
    ok, err = validate_tool_params("nonexistent_tool", {})
    assert ok is False


def test_count_rejects_invalid_values():
    for value in ("500", "abc", -1, 0, True, 1.5):
        ok, _ = validate_tool_params("clear_messages", {"count": value})
        assert ok is False
    params = {"count": "50"}
    ok, _ = validate_tool_params("clear_messages", params)
    assert ok and params["count"] == 50


def test_seconds_validation():
    params = {"seconds": "120"}
    ok, _ = validate_tool_params("set_slowmode", params)
    assert ok is True
    assert params["seconds"] == 120

    params = {"seconds": "99999"}
    ok, err = validate_tool_params("set_slowmode", params)
    assert ok is False
    assert "21600" in err

    params = {"seconds": "abc"}
    ok, err = validate_tool_params("set_slowmode", params)
    assert ok is False


def test_set_slowmode_no_required_fields():
    ok, _ = validate_tool_params("set_slowmode", {})
    assert ok is True


def test_get_user_info_optional_user():
    ok, _ = validate_tool_params("get_user_info", {})
    assert ok is True
