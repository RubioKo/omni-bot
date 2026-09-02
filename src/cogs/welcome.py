import discord
from discord.ext import commands
import logging

logger = logging.getLogger("OmniBot.welcome")

WELCOME_DM_TEMPLATE = """Bienvenido a **OmniBot**!

Somos una comunidad con {member_count}+ miembros.

Para acceder al servidor lee y acepta las reglas en Discord.
Una vez aceptadas, ve a #roles para elegir tus juegos.

Juegos disponibles:
{games}

Usa /guia para ver todos los comandos.
Problemas? Contacta a un @moderador.

Te esperamos dentro!"""


def _build_welcome_message(member: discord.Member) -> str:
    from .roles import GAME_ROLES
    game_lines = [f"- {name.split(' ', 1)[1]}" for name in GAME_ROLES]
    return WELCOME_DM_TEMPLATE.format(
        member_count=member.guild.member_count or 0,
        games="\n".join(game_lines),
    )


class WelcomeCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.Cog.listener()
    async def on_member_join(self, member):
        logger.info(f"New member: {member}")

        miembro_role = discord.utils.get(member.guild.roles, name="Miembro")
        if miembro_role:
            try:
                await member.add_roles(miembro_role, reason="Nuevo miembro")
                logger.info(f"Assigned Miembro to {member}")
            except discord.Forbidden:
                logger.warning(f"Could not assign Miembro to {member}")

        try:
            await member.send(_build_welcome_message(member))
        except discord.Forbidden:
            pass

    @commands.Cog.listener()
    async def on_member_remove(self, member):
        logger.info(f"Member left: {member}")


async def setup(bot):
    await bot.add_cog(WelcomeCog(bot))
