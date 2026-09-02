from datetime import datetime, timedelta, timezone

from src.cogs.automod import (
    AutoModCog,
    contains_banned_word,
    count_emojis,
    count_mentions,
    get_banned_words,
    is_excessive_caps,
    normalize_text,
    should_flag_new_account,
)


def make_cog():
    return AutoModCog(bot=None)


def test_extract_domain_basic():
    cog = make_cog()
    assert cog._extract_domain("https://www.youtube.com/watch?v=abc") == "youtube.com"
    assert cog._extract_domain("http://discord.gg/invite") == "discord.gg"
    assert cog._extract_domain("https://github.com/user/repo") == "github.com"


def test_extract_domain_strips_www():
    cog = make_cog()
    assert cog._extract_domain("https://www.reddit.com/r/test") == "reddit.com"


def test_extract_domain_without_scheme():
    cog = make_cog()
    assert cog._extract_domain("www.twitch.tv/streamer") == "twitch.tv"
    assert cog._extract_domain("discord.gg/xyz") == "discord.gg"


def test_extract_domain_malformed():
    cog = make_cog()
    assert cog._extract_domain("not a url at all") == ""


def test_is_safe_domain_exact():
    cog = make_cog()
    assert cog._is_safe_domain("youtube.com") is True
    assert cog._is_safe_domain("discord.gg") is True


def test_is_safe_domain_subdomain():
    cog = make_cog()
    assert cog._is_safe_domain("www.youtube.com") is True
    assert cog._is_safe_domain("i.imgur.com") is True
    assert cog._is_safe_domain("open.spotify.com") is True


def test_is_safe_domain_blocked():
    cog = make_cog()
    assert cog._is_safe_domain("evil-site.com") is False
    assert cog._is_safe_domain("scam.example.com") is False


def test_is_safe_domain_not_youtube_imposter():
    cog = make_cog()
    assert cog._is_safe_domain("youtube.com.evil.com") is False


def test_normalize_text_leet_and_case():
    assert normalize_text("P3ND3J0") == "pendejo"
    assert normalize_text("M1ERD4") == "mierda"
    assert normalize_text("  HIJO   DE   PUTA ") == "hijo de puta"


def test_contains_banned_word_single():
    words = ["puto", "mierda"]
    assert contains_banned_word("eres un puto", words) is True
    assert contains_banned_word("que mierda es esto", words) is True
    assert contains_banned_word("todo bien", words) is False


def test_contains_banned_word_word_boundary():
    words = ["puta"]
    assert contains_banned_word("puta vida", words) is True
    assert contains_banned_word("computadora", words) is False
    assert contains_banned_word("disputa", words) is False


def test_contains_banned_word_leetspeak():
    words = ["pendejo"]
    assert contains_banned_word("sos un p3nd3j0", words) is True


def test_contains_banned_word_phrase():
    words = ["hijo de puta"]
    assert contains_banned_word("eres un hijo de puta", words) is True
    assert contains_banned_word("hijoputa", words) is False


def test_contains_banned_word_default_list():
    words = get_banned_words()
    assert len(words) > 10
    assert "puta" in words
    assert "hijo de puta" in words


def test_contains_banned_word_config_extra(monkeypatch):
    from src.config import config
    monkeypatch.setattr(config, "banned_words", "cucaracha, zapallo")
    words = get_banned_words()
    assert "cucaracha" in words
    assert "zapallo" in words


def test_count_mentions():
    assert count_mentions("hola <@123> <@456>") == 2
    assert count_mentions("<@!789> y <@&111>") == 2
    assert count_mentions("sin menciones") == 0


def test_is_excessive_caps_true():
    assert is_excessive_caps("QUE HACES TODO BIEN?") is True


def test_is_excessive_caps_false():
    assert is_excessive_caps("Que haces todo bien?") is False
    assert is_excessive_caps("OK") is False
    assert is_excessive_caps("1234567890 !!!") is False


def test_count_emojis():
    assert count_emojis("😂😂😂") == 3
    assert count_emojis("<:pepe:123456789> x2") == 1
    assert count_emojis("hola") == 0


def test_should_flag_new_account():
    now = datetime(2026, 8, 23, tzinfo=timezone.utc)
    fresh = now - timedelta(days=2)
    old = now - timedelta(days=30)
    assert should_flag_new_account(fresh, 7, now) is True
    assert should_flag_new_account(old, 7, now) is False
    assert should_flag_new_account(None, 7, now) is False
