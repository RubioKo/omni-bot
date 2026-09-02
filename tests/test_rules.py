from src.services.rules import RULES, RULES_FOOTER, build_rules_embed


def test_rules_count():
    assert len(RULES) == 9


def test_rules_structure():
    for entry in RULES:
        assert len(entry) == 3
        name, emoji, value = entry
        assert name[0].isdigit()
        assert emoji
        assert len(value) > 10


def test_rules_embed_fields():
    embed = build_rules_embed()
    assert len(embed.fields) == 9
    assert "aceptas estas reglas" in (embed.description or "")
    assert embed.footer.text == RULES_FOOTER


def test_rules_embed_custom_title():
    embed = build_rules_embed(title="REGLAS CUSTOM")
    assert embed.title == "REGLAS CUSTOM"
