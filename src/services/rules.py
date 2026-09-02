import discord

RULES = [
    ("1. RESPETO MUTUO", "🤝", "Trata a todos con respeto. No se tolera bullying, acoso, discriminación ni insultos personales."),
    ("2. CONTENIDO APROPIADO", "📵", "No compartas contenido NSFW, gore, ilegal o que viole los ToS de Discord."),
    ("3. SIN SPAM", "🚫", "No hagas spam de canales, mensajes, emojis o links. Auto-promoción solo en canales designados."),
    ("4. CANALES CORRECTOS", "🎯", "Usa cada canal para su propósito. Contenido off-topic va en #off-topic."),
    ("5. SIN TOXICIDAD", "😤", "No seas tóxico en juegos ni en el chat. Competencia sana, no odio."),
    ("6. PRIVACIDAD", "🔒", "No compartas información personal de otros miembros (doxxing)."),
    ("7. CUENTAS ALT", "👥", "No evadas bans o sanciones con cuentas alternativas."),
    ("8. STAFF TIENE LA ÚLTIMA PALABRA", "⚖️", "Las decisiones del staff son finales. Si no estás de acuerdo, habla por DM."),
    ("9. DIVIÉRTETE", "🎉", "Estamos aquí para jugar y pasarla bien. ¡Disfruta la comunidad!"),
]

RULES_FOOTER = "OmniBot | Actualizado Agosto 2026"

RULES_INTRO = (
    "Lee y respeta las siguientes reglas. "
    "El incumplimiento puede resultar en sanciones.\n"
    "Al estar en el servidor **aceptas estas reglas**."
)


def build_rules_embed(title: str | None = None) -> discord.Embed:
    embed = discord.Embed(
        title=title or "📜 REGLAS DEL SERVIDOR",
        description=RULES_INTRO,
        color=0xFF0000,
    )
    for name, emoji, value in RULES:
        embed.add_field(name=f"{emoji} {name}", value=value, inline=False)
    embed.set_footer(text=RULES_FOOTER)
    return embed
