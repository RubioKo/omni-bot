from src.utils.helpers import parse_duration


def test_parse_duration_single_units():
    assert parse_duration("30s") == 30
    assert parse_duration("10m") == 600
    assert parse_duration("2h") == 7200
    assert parse_duration("1d") == 86400


def test_parse_duration_combined():
    assert parse_duration("1h30m") == 5400
    assert parse_duration("2h 15m 30s") == 8130


def test_parse_duration_invalid_returns_zero():
    assert parse_duration("banana") == 0
    assert parse_duration("") == 0
    assert parse_duration("10") == 0


def test_parse_duration_case_insensitive():
    assert parse_duration("10M") == 600
    assert parse_duration("1H") == 3600


def test_parse_duration_min_alias():
    assert parse_duration("5min") == 300
    assert parse_duration("90min") == 5400


def test_parse_duration_multi_unit_mix():
    assert parse_duration("10m 30s") == 630
    assert parse_duration("1d 12h") == 129600
