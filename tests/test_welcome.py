from src.cogs.welcome import _build_welcome_message


class FakeGuild:
    def __init__(self, count):
        self.member_count = count


class FakeMember:
    def __init__(self, count):
        self.guild = FakeGuild(count)


def test_welcome_message_dynamic_member_count():
    msg = _build_welcome_message(FakeMember(150))
    assert "150+" in msg
    assert "145" not in msg


def test_welcome_message_contains_games():
    msg = _build_welcome_message(FakeMember(1))
    for game in ("Valorant Player", "Fortnite Player", "Genshin Player", "HotS Player"):
        assert game in msg


def test_welcome_message_excludes_removed_games():
    msg = _build_welcome_message(FakeMember(1))
    assert "WoW Player" not in msg
    assert "7 Days Player" not in msg


def test_welcome_message_zero_count():
    msg = _build_welcome_message(FakeMember(None))
    assert "0+" in msg
