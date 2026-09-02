import discord
from discord import ui
import logging

logger = logging.getLogger("OmniBot.roles")

GAME_ROLES = {
    "🔫 Valorant Player": {"emoji": "🔫", "description": "Valorant"},
    "🏗️ Fortnite Player": {"emoji": "🏗️", "description": "Fortnite"},
    "⚔️ LoL Player": {"emoji": "⚔️", "description": "League of Legends"},
    "🎯 Arena Breakout Player": {"emoji": "🎯", "description": "Arena Breakout Infinite"},
    "🌸 Genshin Player": {"emoji": "🌸", "description": "Genshin Impact"},
    "⚔️ HotS Player": {"emoji": "⚔️", "description": "Heroes of the Storm"},
}

EXTRA_ROLES = {
    "🏆 Competitive": {"emoji": "🏆", "description": "Jugadores competitivos"},
    "😎 Casual": {"emoji": "😎", "description": "Jugadores casuales"},
    "🎬 Creador": {"emoji": "🎬", "description": "Creador de contenido / Streamer"},
    "👥 LFG": {"emoji": "👥", "description": "Recibir pings de LFG"},
}


async def _toggle_roles(interaction, roles_dict, added, removed):
    member = interaction.user
    guild = interaction.guild
    for role_name in roles_dict:
        role = discord.utils.get(guild.roles, name=role_name)
        if not role:
            continue
        try:
            if role in member.roles:
                await member.remove_roles(role)
                removed.append(role_name)
            else:
                await member.add_roles(role)
                added.append(role_name)
        except discord.Forbidden:
            logger.warning(f"No se pudo modificar el rol {role_name} de {member}")
        except discord.HTTPException as e:
            logger.error(f"Error al modificar rol {role_name}: {e}")


class GameRoleSelect(ui.Select):
    def __init__(self):
        options = [
            discord.SelectOption(
                label=name.split(" ", 1)[1] if " " in name else name,
                value=name,
                emoji=data["emoji"],
                description=data["description"]
            )
            for name, data in GAME_ROLES.items()
        ]
        super().__init__(
            custom_id="roles_games",
            placeholder="Selecciona tus juegos...",
            min_values=0,
            max_values=len(options),
            options=options
        )

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        added, removed = [], []
        await _toggle_roles(interaction, self.values, added, removed)
        response = []
        if added:
            response.append(f"Agregados: {', '.join(added)}")
        if removed:
            response.append(f"Removidos: {', '.join(removed)}")
        if not response:
            response.append("No se modificaron roles")
        await interaction.followup.send("\n".join(response), ephemeral=True)


class ExtraRoleSelect(ui.Select):
    def __init__(self):
        options = [
            discord.SelectOption(
                label=name.split(" ", 1)[1] if " " in name else name,
                value=name,
                emoji=data["emoji"],
                description=data["description"]
            )
            for name, data in EXTRA_ROLES.items()
        ]
        super().__init__(
            custom_id="roles_extra",
            placeholder="Estilo de juego y extras...",
            min_values=0,
            max_values=len(options),
            options=options
        )

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        added, removed = [], []
        await _toggle_roles(interaction, self.values, added, removed)
        response = []
        if added:
            response.append(f"Agregados: {', '.join(added)}")
        if removed:
            response.append(f"Removidos: {', '.join(removed)}")
        if not response:
            response.append("No se modificaron roles")
        await interaction.followup.send("\n".join(response), ephemeral=True)


class RoleView(ui.View):
    def __init__(self):
        super().__init__(timeout=None)
        self.add_item(GameRoleSelect())
        self.add_item(ExtraRoleSelect())


async def setup_role_channel(bot, channel):
    embed = discord.Embed(
        title="ELIGE TUS ROLES",
        description=(
            "Selecciona tus juegos favoritos para desbloquear canales.\n"
            "Tambien puedes elegir tu estilo de juego y extras.\n\n"
            "**Juegos** - Desbloquea canales especificos\n"
            "**Estilo** - Competitive, Casual, Creador, LFG"
        ),
        color=0x5865F2
    )
    embed.set_footer(text="OmniBot | Selecciona con los menus de abajo")
    view = RoleView()
    await channel.send(embed=embed, view=view)
    logger.info(f"Role selection message sent to #{channel.name}")
