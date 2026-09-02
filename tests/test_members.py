from src.utils.members import resolve_member


class FakeRole:
    def __init__(self, name):
        self.name = name


class FakeMember:
    def __init__(self, member_id, name, nick=None):
        self.id = member_id
        self.name = name
        self.nick = nick
        self.roles = [FakeRole("@everyone")]


class FakeGuild:
    def __init__(self, members):
        self.members = members

    def get_member(self, member_id):
        for m in self.members:
            if m.id == member_id:
                return m
        return None


GUILD = FakeGuild([
    FakeMember(1, "Pepito"),
    FakeMember(2, "Pepe", nick="Pepesaurio"),
    FakeMember(3, "ab", nick=None),
    FakeMember(4, "abby"),
    FakeMember(5, "Juan Carlos"),
])


def test_resolve_by_mention():
    member = resolve_member(GUILD, "<@3>")
    assert member is not None
    assert member.id == 3


def test_resolve_by_mention_exclamation():
    member = resolve_member(GUILD, "<@!4>")
    assert member.id == 4


def test_resolve_exact_name():
    member = resolve_member(GUILD, "Pepito")
    assert member.id == 1


def test_resolve_exact_nick():
    member = resolve_member(GUILD, "Pepesaurio")
    assert member.id == 2


def test_resolve_case_insensitive():
    member = resolve_member(GUILD, "pepito")
    assert member.id == 1


def test_resolve_prefix_wins_over_substring():
    member = resolve_member(GUILD, "ab")
    assert member.id == 3


def test_resolve_substring_fallback():
    member = resolve_member(GUILD, "bb")
    assert member.id == 4


def test_resolve_no_match():
    assert resolve_member(GUILD, "zzz") is None


def test_resolve_empty():
    assert resolve_member(GUILD, "") is None
    assert resolve_member(None, "pepe") is None
