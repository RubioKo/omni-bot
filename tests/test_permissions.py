from src.services.permissions import PermissionManager, PermissionLevel


class FakeRole:
    def __init__(self, name):
        self.name = name


class FakeMember:
    def __init__(self, roles, member_id=1):
        self.roles = roles
        self.id = member_id


def make_member(*role_names, member_id=1):
    return FakeMember([FakeRole(n) for n in role_names], member_id=member_id)


def test_member_default_level():
    m = make_member("😎 CASUAL")
    pm = PermissionManager()
    assert pm.get_permission_level(m) == PermissionLevel.MEMBER


def test_dj_level():
    m = make_member("DJ")
    pm = PermissionManager()
    assert pm.get_permission_level(m) == PermissionLevel.DJ


def test_vip_level():
    m = make_member("🏆 VIP")
    pm = PermissionManager()
    assert pm.get_permission_level(m) == PermissionLevel.VIP


def test_moderator_level():
    m = make_member("MODERADOR")
    pm = PermissionManager()
    assert pm.get_permission_level(m) == PermissionLevel.MODERATOR


def test_admin_level():
    m = make_member("ADMINISTRADOR")
    pm = PermissionManager()
    assert pm.get_permission_level(m) == PermissionLevel.ADMIN


def test_owner_level():
    m = make_member("PROPIETARIO")
    pm = PermissionManager()
    assert pm.get_permission_level(m) == PermissionLevel.OWNER


def test_case_insensitive_roles():
    m = make_member("moderador")
    pm = PermissionManager()
    assert pm.get_permission_level(m) == PermissionLevel.MODERATOR


def test_highest_role_wins():
    m = make_member("😎 CASUAL", "DJ", "MODERADOR")
    pm = PermissionManager()
    assert pm.get_permission_level(m) == PermissionLevel.MODERATOR


def test_has_permission_moderator():
    pm = PermissionManager()
    mod = make_member("MODERADOR")
    assert pm.has_permission(mod, "warn_user") is True
    assert pm.has_permission(mod, "clear_messages") is False


def test_has_permission_member_denied():
    pm = PermissionManager()
    member = make_member("😎 CASUAL")
    assert pm.has_permission(member, "warn_user") is False
    assert pm.has_permission(member, "get_server_stats") is True


def test_required_level_name():
    pm = PermissionManager()
    assert pm.get_required_level_name("warn_user") == "MODERADOR"
    assert pm.get_required_level_name("clear_messages") == "ADMINISTRADOR"
    assert pm.get_required_level_name("play_music") == "DJ"
    assert pm.get_required_level_name("unknown_cmd") == "PROPIETARIO"


def test_permission_name_dj():
    pm = PermissionManager()
    dj = make_member("DJ")
    assert pm.get_permission_name(dj) == "DJ"


def test_consume_rate_limit_atomic():
    pm = PermissionManager()
    m = make_member("😎 CASUAL", member_id=77)
    for _ in range(5):
        ok, _ = pm.consume_rate_limit(m)
        assert ok is True
    ok, wait = pm.consume_rate_limit(m)
    assert ok is False
    assert wait > 0


def test_consume_rate_limit_owner_never_blocked():
    pm = PermissionManager()
    owner = make_member("PROPIETARIO", member_id=88)
    for _ in range(50):
        ok, _ = pm.consume_rate_limit(owner)
        assert ok is True
