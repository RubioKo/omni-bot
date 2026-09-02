import wavelink

from src.cogs.music import AUTOPLAY_MODE, decide_play_action, format_duration, display_title, LONG_MAX


def test_decide_play_action_radio_replaces():
    assert decide_play_action(was_radio=True, is_playing=True) == "replace"
    assert decide_play_action(was_radio=True, is_playing=False) == "replace"


def test_decide_play_action_user_music_queues():
    assert decide_play_action(was_radio=False, is_playing=True) == "queue"


def test_decide_play_action_nothing_playing_plays():
    assert decide_play_action(was_radio=False, is_playing=False) == "play"


def test_format_duration_live_values():
    assert format_duration(None) == "Live"
    assert format_duration(0) == "Live"
    assert format_duration(-5) == "Live"
    assert format_duration(LONG_MAX) == "Live"


def test_format_duration_minutes_seconds():
    assert format_duration(61000) == "1:01"
    assert format_duration(59000) == "0:59"


def test_format_duration_hours():
    assert format_duration(3661000) == "1:01:01"
    assert format_duration(7200000) == "2:00:00"


def test_display_title():
    class FakeTrack:
        title = "  Song Name  "

    assert display_title(FakeTrack()) == "Song Name"

    class EmptyTrack:
        title = ""

    assert display_title(EmptyTrack()) == "Radio en vivo"


def test_radio_streams_only_valid_stations():
    from src.cogs.music import RADIO_STREAMS
    assert "rock" in RADIO_STREAMS
    assert "lofi" in RADIO_STREAMS
    assert "gaming" not in RADIO_STREAMS
    for station in RADIO_STREAMS.values():
        assert station["url"].startswith("https://")


def test_autoplay_mode_is_partial():
    assert AUTOPLAY_MODE is wavelink.AutoPlayMode.partial
