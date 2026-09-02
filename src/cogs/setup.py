import discord
from discord import app_commands
from discord.ext import commands
import logging

logger = logging.getLogger("OmniBot.setup")

OWNER_ROLE_NAMES = {"PROPIETARIO", "G/M", "ADMINISTRADOR", "MODERADOR"}


class ConfirmView(discord.ui.View):
    def __init__(self, owner_id):
        super().__init__(timeout=60)
        self.owner_id = owner_id
        self.confirmed = False

    @discord.ui.button(label="CONFIRMAR", style=discord.ButtonStyle.danger)
    async def confirm(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.owner_id:
            await interaction.response.send_message("Solo el PROPIETARIO puede confirmar.", ephemeral=True)
            return
        self.confirmed = True
        await interaction.response.send_message("Ejecutando...", ephemeral=True)
        self.stop()

    @discord.ui.button(label="CANCELAR", style=discord.ButtonStyle.secondary)
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.owner_id:
            await interaction.response.send_message("Solo el PROPIETARIO puede cancelar.", ephemeral=True)
            return
        await interaction.response.send_message("Cancelado.", ephemeral=True)
        self.stop()

    async def on_timeout(self):
        self.stop()


class SetupCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    async def _is_owner(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != interaction.guild.owner_id:
            await interaction.followup.send("Solo el PROPIETARIO puede usar este comando.")
            return False
        return True

    @app_commands.command(name="nuke-all", description="Destruir estructura del servidor")
    async def nuke_all(self, interaction: discord.Interaction):
        if not await self._is_owner(interaction):
            return

        guild = interaction.guild
        extra_roles = [r for r in guild.roles if r.name not in OWNER_ROLE_NAMES and r.name != "@everyone"]
        role_names = ", ".join([r.name for r in extra_roles[:15]]) or "Ninguno"

        embed = discord.Embed(
            title="DESTRUIR SERVIDOR",
            description=(
                f"Se eliminaran:\n"
                f"- {len(guild.categories)} categorias\n"
                f"- {len(guild.channels)} canales\n"
                f"- {len(extra_roles)} roles: {role_names}\n\n"
                f"NO se expulsara ningun miembro.\n"
                f"NO se eliminaran: PROPIETARIO, G/M, MODERADOR, ADMINISTRADOR\n\n"
                f"ACCION IRREVERSIBLE"
            ),
            color=0xFF0000
        )
        view = ConfirmView(interaction.user.id)
        await interaction.response.send_message(embed=embed, view=view)
        await view.wait()

        if not view.confirmed:
            await interaction.edit_original_response(content="Cancelado.", embed=None)
            return

        deleted_ch = 0
        for ch in guild.channels[:]:
            try:
                await ch.delete()
                deleted_ch += 1
            except Exception as e:
                logger.error(f"Error deleting {ch.name}: {e}")

        deleted_cat = 0
        for cat in guild.categories[:]:
            try:
                await cat.delete()
                deleted_cat += 1
            except Exception as e:
                logger.error(f"Error deleting {cat.name}: {e}")

        deleted_roles = 0
        for role in guild.roles[:]:
            if role.name in OWNER_ROLE_NAMES or role.name == "@everyone":
                continue
            try:
                await role.delete()
                deleted_roles += 1
            except Exception as e:
                logger.error(f"Error deleting {role.name}: {e}")

        await interaction.edit_original_response(
            content=(
                f"Servidor destruido.\n"
                f"Canales: {deleted_ch} | Categorias: {deleted_cat} | Roles: {deleted_roles}\n"
                f"Usa `/deploy` para construir la nueva estructura."
            )
        )

    @app_commands.command(name="deploy", description="Construir estructura del servidor")
    async def deploy(self, interaction: discord.Interaction):
        if not await self._is_owner(interaction):
            return

        guild = interaction.guild
        embed = discord.Embed(
            title="CONSTRUIR SERVIDOR",
            description=(
                "Nueva estructura optimizada:\n"
                "- 6 categorias\n"
                "- ~20 canales\n"
                "- 14 roles\n"
                "- Forum #lfg\n"
                "- Announcement #anuncios\n"
                "- Niveles de XP\n\n"
                "Ejecutar ahora?"
            ),
            color=0x57F287
        )
        view = ConfirmView(interaction.user.id)
        await interaction.response.send_message(embed=embed, view=view)
        await view.wait()

        if not view.confirmed:
            await interaction.edit_original_response(content="Cancelado.", embed=None)
            return

        await interaction.edit_original_response(content="Creando roles...")

        roles_to_create = [
            ("Miembro", 0x99AAB5),
            ("DJ", 0x1DB954),
            ("🔫 Valorant Player", 0xED4245),
            ("🏗️ Fortnite Player", 0x57F287),
            ("⚔️ LoL Player", 0xFEE75C),
            ("🎯 Arena Breakout Player", 0x5865F2),
            ("🌸 Genshin Player", 0xFFB7C5),
            ("⚔️ HotS Player", 0x00BFFF),
            ("🏆 Competitive", 0xE74C3C),
            ("😎 Casual", 0x3498DB),
            ("🎬 Creador", 0x9B59B6),
            ("👥 LFG", 0x2ECC71),
            ("🛡️ Staff Helper", 0x00CED1),
            ("🏆 VIP", 0xFFD700),
        ]

        created_roles = {}
        for role_name, color in roles_to_create:
            existing = discord.utils.get(guild.roles, name=role_name) or created_roles.get(role_name)
            if not existing:
                try:
                    role = await guild.create_role(name=role_name, color=discord.Color(color))
                    created_roles[role_name] = role
                except Exception as e:
                    logger.error(f"Error creating {role_name}: {e}")
            else:
                created_roles[role_name] = existing

        miembro = created_roles.get("Miembro")
        if not miembro:
            await interaction.edit_original_response(
                content="❌ No se pudo crear el rol **Miembro** (permisos insuficientes). "
                "Crea el rol manualmente y vuelve a ejecutar `/deploy`."
            )
            return

        everyone = guild.default_role
        no_access = discord.PermissionOverwrite(read_messages=False)
        read_only = discord.PermissionOverwrite(
            read_messages=True, send_messages=False, add_reactions=True,
            embed_links=True, read_message_history=True,
        )
        public = discord.PermissionOverwrite(
            read_messages=True, send_messages=True, add_reactions=True,
            embed_links=True, attach_files=True, read_message_history=True,
            external_emojis=True, create_public_threads=True, send_messages_in_threads=True,
        )
        voice_all = discord.PermissionOverwrite(
            read_messages=True, connect=True, speak=True,
            use_voice_activation=True, stream=True,
        )

        await interaction.edit_original_response(content=f"{len(created_roles)} roles creados. Construyendo canales...")

        categories = [
            {
                "name": "INFORMACION",
                "base_perms": {everyone: no_access, miembro: read_only},
                "channels": [
                    ("reglas", "text", "Lee y acepta las reglas antes de participar."),
                    ("roles", "text", "Elige tus juegos y roles con los menus de abajo."),
                ],
                "announcements": [
                    ("anuncios", "Anuncios oficiales del staff."),
                ],
            },
            {
                "name": "COMUNIDAD",
                "base_perms": {everyone: no_access, miembro: public},
                "channels": [
                    ("general", "text", "Chat principal de la comunidad."),
                    ("off-topic", "text", "Charla libre sobre cualquier tema."),
                    ("memes", "text", "Comparte memes y diviertete."),
                    ("clips-y-logros", "text", "Tus mejores jugadas, logros y pantallazos."),
                    ("presentaciones", "text", "Presentate a la comunidad."),
                ],
            },
            {
                "name": "JUEGOS",
                "base_perms": {everyone: no_access, miembro: no_access},
                "game_overrides": {
                    "🔫 Valorant Player": ["valorant"],
                    "🏗️ Fortnite Player": ["fortnite"],
                    "⚔️ LoL Player": ["lol"],
                    "🎯 Arena Breakout Player": ["abi"],
                    "🌸 Genshin Player": ["genshin"],
                    "⚔️ HotS Player": ["hots"],
                },
                "forum_channels": [
                    ("lfg", "Busca grupo para cualquier juego. Usa los tags por juego."),
                ],
                "channels": [
                    ("valorant", "text", "Valorant: agentes, mapas, ranked."),
                    ("fortnite", "text", "Fortnite: battle royale, creative, torneos."),
                    ("lol", "text", "League of Legends: lineas, builds, ranked."),
                    ("abi", "text", "Arena Breakout Infinite: extraccion, loot, mapas."),
                    ("genshin", "text", "Genshin Impact: personajes, artefactos, abismo."),
                    ("hots", "text", "Heroes of the Storm: heroes, mapas, estrategias."),
                ],
            },
            {
                "name": "EVENTOS",
                "base_perms": {everyone: no_access, miembro: public},
                "channels": [
                    ("game-nights", "text", "Organiza noches de juegos con la comunidad."),
                    ("coach-corner", "text", "Veteranos ayudan a nuevos. Pregunta sin miedo."),
                    ("sugerencias", "text", "Ideas para mejorar el servidor. El staff lee todo."),
                ],
            },
            {
                "name": "VOZ",
                "base_perms": {everyone: no_access, miembro: voice_all},
                "voice_channels": [
                    "General",
                    "Gaming",
                    "Music",
                    "AFK",
                ],
            },
            {
                "name": "STAFF",
                "base_perms": {everyone: no_access, miembro: no_access},
                "staff_roles": ["MODERADOR", "G/M", "ADMINISTRADOR", "🛡️ Staff Helper"],
                "channels": [
                    ("staff-chat", "text", "Chat interno del equipo."),
                    ("mod-logs", "text", "Logs automaticos de moderacion."),
                ],
                "voice_channels": [
                    "Staff Only",
                ],
            },
        ]

        created_channels = 0
        channel_map = {}

        for cat_config in categories:
            cat = discord.utils.get(guild.categories, name=cat_config["name"])
            if not cat:
                try:
                    cat = await guild.create_category(cat_config["name"])
                except Exception as e:
                    logger.error(f"Error creating {cat_config['name']}: {e}")
                    continue
            else:
                for ch in cat.channels:
                    try:
                        await ch.delete()
                    except Exception:
                        pass

            for role, perms in cat_config.get("base_perms", {}).items():
                if role:
                    try:
                        await cat.set_permissions(role, overwrite=perms)
                    except Exception as e:
                        logger.error(f"Perms error {role} in {cat.name}: {e}")

            for staff_name in cat_config.get("staff_roles", []):
                staff_role = created_roles.get(staff_name) or discord.utils.get(guild.roles, name=staff_name)
                if staff_role:
                    try:
                        await cat.set_permissions(staff_role, overwrite=public)
                    except Exception as e:
                        logger.error(f"Staff perms error: {e}")

            for ch_name, ch_type, ch_topic in cat_config.get("channels", []):
                existing = discord.utils.get(guild.channels, name=ch_name)
                if existing:
                    try:
                        await existing.delete()
                    except Exception:
                        pass
                try:
                    ch = await guild.create_text_channel(ch_name, category=cat, topic=ch_topic)
                    channel_map[ch_name] = ch
                    created_channels += 1
                    if ch_name in ["reglas", "roles"]:
                        await ch.set_permissions(everyone, overwrite=read_only)
                except Exception as e:
                    logger.error(f"Error creating {ch_name}: {e}")

            for role_name, game_chs in cat_config.get("game_overrides", {}).items():
                game_role = created_roles.get(role_name)
                if game_role:
                    for gch_name in game_chs:
                        gch = channel_map.get(gch_name)
                        if gch:
                            try:
                                await gch.set_permissions(game_role, overwrite=public)
                            except Exception as e:
                                logger.error(f"Error setting {role_name} perms on {gch_name}: {e}")

            for ch_name, ch_topic in cat_config.get("announcements", []):
                existing = discord.utils.get(guild.channels, name=ch_name)
                if existing:
                    try:
                        await existing.delete()
                    except Exception:
                        pass
                try:
                    ch = await guild.create_text_channel(
                        ch_name, category=cat, topic=ch_topic,
                        news=True,
                    )
                    channel_map[ch_name] = ch
                    created_channels += 1
                    await ch.set_permissions(everyone, overwrite=read_only)
                except Exception as e:
                    logger.error(f"Error creating {ch_name}: {e}")

            for vc_name in cat_config.get("voice_channels", []):
                prefixed = f"🔊 {vc_name}" if not vc_name.startswith("🔊") else vc_name
                existing = discord.utils.get(guild.channels, name=prefixed)
                if existing:
                    try:
                        await existing.delete()
                    except Exception:
                        pass
                try:
                    ch = await guild.create_voice_channel(prefixed, category=cat)
                    channel_map[vc_name] = ch
                    created_channels += 1
                except Exception as e:
                    logger.error(f"Error creating VC {vc_name}: {e}")

            for forum_name, forum_topic in cat_config.get("forum_channels", []):
                existing = discord.utils.get(guild.channels, name=forum_name)
                if existing:
                    try:
                        await existing.delete()
                    except Exception:
                        pass
                try:
                    ch = await guild.create_forum_channel(
                        forum_name, category=cat, topic=forum_topic,
                    )
                    channel_map[forum_name] = ch
                    created_channels += 1
                    await ch.set_permissions(miembro, overwrite=public)
                except Exception as e:
                    logger.error(f"Error creating forum {forum_name}: {e}")

        await interaction.edit_original_response(content=f"{created_channels} canales creados. Publicando contenido...")

        reglas_ch = channel_map.get("reglas")
        if reglas_ch:
            try:
                from ..services.rules import build_rules_embed
                embed = build_rules_embed(title="REGLAS DEL SERVIDOR")
                await reglas_ch.send(embed=embed)
            except Exception as e:
                logger.error(f"Error posting rules: {e}")

        roles_ch = channel_map.get("roles")
        if roles_ch:
            try:
                from ..cogs.roles import setup_role_channel
                await setup_role_channel(self.bot, roles_ch)
            except Exception as e:
                logger.error(f"Error setting roles: {e}")

        anuncios_ch = channel_map.get("anuncios")
        if anuncios_ch:
            try:
                await anuncios_ch.send(embed=discord.Embed(
                    title="ANUNCIOS",
                    description="Canal oficial de anuncios del staff del servidor.",
                    color=0x5865F2
                ))
            except Exception as e:
                logger.error(f"Error posting anuncios: {e}")

        game_content = {
            "valorant": ("VALORANT", "Agentes, mapas, ranked. Clips en #clips-y-logros.", 0xED4245),
            "fortnite": ("FORTNITE", "Battle royale, creative, torneos. Clips en #clips-y-logros.", 0x57F287),
            "lol": ("LEAGUE OF LEGENDS", "Lineas, builds, ranked. Usa u.gg y op.gg.", 0xFEE75C),
            "abi": ("ARENA BREAKOUT INFINITE", "Extraccion, loot, mapas. Coordina raids en #lfg.", 0x5865F2),
            "genshin": ("GENSHIN IMPACT", "Personajes, artefactos, abismo. Comparte tus pulls.", 0xFFB7C5),
            "hots": ("HEROES OF THE STORM", "Heroes, mapas, estrategias. Busca grupo en #lfg.", 0x00BFFF),
            "game-nights": ("GAME NIGHTS", "Organiza y vota noches de juegos. Propone fecha y juego.", 0x1ABC9C),
            "coach-corner": ("COACH CORNER", "Veteranos ofrecen ayuda. Pregunta libremente.", 0xE67E22),
            "sugerencias": ("SUGERENCIAS", "Ideas para mejorar. Cada sugerencia es leida.", 0x3498DB),
            "presentaciones": ("PRESENTACIONES", "Cuentanos:\n- Como te llaman\n- Que juegas\n- Que buscas en la comunidad", 0x57F287),
            "clips-y-logros": ("CLIPS Y LOGROS", "Comparte tus mejores jugadas, logros y pantallazos.", 0x9B59B6),
        }

        for ch_name, (title, desc, color) in game_content.items():
            ch = channel_map.get(ch_name)
            if ch:
                try:
                    await ch.send(embed=discord.Embed(title=title, description=desc, color=discord.Color(color)))
                except Exception as e:
                    logger.error(f"Error posting to {ch_name}: {e}")

        lfg_ch = channel_map.get("lfg")
        if lfg_ch:
            try:
                await lfg_ch.send(embed=discord.Embed(
                    title="LOOKING FOR GROUP",
                    description=(
                        "Encuentra grupo para cualquier juego.\n\n"
                        "Usa los **tags** para indicar el juego.\n"
                        "Incluye en tu post: juego, horario, nivel/rank, que buscas."
                    ),
                    color=0x2ECC71
                ))
            except Exception as e:
                logger.error(f"Error posting LFG: {e}")

        await interaction.edit_original_response(content=(
            f"**SERVIDOR DESPLEGADO**\n"
            f"Categorias: 6 | Canales: {created_channels} | Roles: {len(created_roles)}\n"
            f"#lfg: Forum | #anuncios: Announcement\n"
            f"Activa **Rules Screening** en Ajustes del Servidor > Safety Setup\n"
            f"Verifica con `/server-map`"
        ))

    @app_commands.command(name="server-map", description="Ver mapa completo del servidor")
    async def server_map(self, interaction: discord.Interaction):
        if not await self._is_owner(interaction):
            return

        guild = interaction.guild
        lines = [f"**MAPA: {guild.name}**"]
        lines.append(f"Miembros: {guild.member_count} | Roles: {len(guild.roles)} | Canales: {len(guild.channels)}\n")

        for cat in guild.categories:
            everyone_overwrite = cat.overwrites_for(guild.default_role)
            vis = "RO" if everyone_overwrite.read_messages is False else "PB"
            lines.append(f"**{cat.name}** [{vis}]")

            text_chs = [c for c in cat.channels if isinstance(c, discord.TextChannel)]
            for ch in text_chs:
                ov = ch.overwrites_for(guild.default_role)
                ch_vis = "RO" if ov.read_messages is False else "PB"
                prefix = "📢 " if ch.is_news() else "#"
                lines.append(f"  [{ch_vis}] {prefix}{ch.name}")

            voice_chs = [c for c in cat.channels if isinstance(c, discord.VoiceChannel)]
            for ch in voice_chs:
                lines.append(f"  [VO] {ch.name}")

            forum_chs = [c for c in cat.channels if isinstance(c, discord.ForumChannel)]
            for ch in forum_chs:
                lines.append(f"  [FORUM] {ch.name}")

            lines.append("")

        lines.append("**ROLES:**")
        for role in guild.roles:
            if role.name != "@everyone":
                lines.append(f"  {role.name} ({len(role.members)} miembros)")

        output = "\n".join(lines)
        for i in range(0, len(output), 2000):
            chunk = output[i:i + 2000]
            if i == 0:
                await interaction.response.send_message(chunk)
            else:
                await interaction.followup.send(chunk)

    @app_commands.command(name="restart-bot", description="Reiniciar el bot")
    async def restart_bot(self, interaction: discord.Interaction):
        if not await self._is_owner(interaction):
            return
        await interaction.response.send_message("Reiniciando...")
        await self.bot.close()

    @app_commands.command(name="repostroles", description="Republicar menus de roles en #roles")
    async def repostroles(self, interaction: discord.Interaction):
        roles_ch = discord.utils.get(interaction.guild.channels, name="roles")
        if not roles_ch:
            await interaction.response.send_message("No encontre el canal #roles.")
            return

        async for msg in roles_ch.history(limit=50):
            if msg.author == self.bot.user:
                await msg.delete()

        from ..cogs.roles import setup_role_channel
        await setup_role_channel(self.bot, roles_ch)
        await interaction.response.send_message("Menus de roles republicados en #roles.")


async def setup(bot):
    await bot.add_cog(SetupCog(bot))
