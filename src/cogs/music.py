import asyncio
import discord
from discord import app_commands
from discord.ext import commands
import logging
import wavelink

from ..services.permissions import permission_manager
from ..services import database as db
from ..config import config

logger = logging.getLogger("OmniBot.music")

RADIO_STREAMS = {
    "lofi": {
        "name": "Lofi Hip Hop",
        "url": "https://play.streamafrica.net/lofiradio",
    },
    "synthwave": {
        "name": "Synthwave",
        "url": "https://streams.ilovemusic.de/iloveradio17.mp3",
    },
    "chill": {
        "name": "Chill Vibes",
        "url": "https://streams.ilovemusic.de/iloveradio2.mp3",
    },
    "pop": {
        "name": "Pop Hits",
        "url": "https://streams.ilovemusic.de/iloveradio3.mp3",
    },
    "rock": {
        "name": "Rock Classics",
        "url": "https://streams.ilovemusic.de/iloveradio4.mp3",
    },
}

autoradio_enabled = {}
autoradio_return_task = {}

LONG_MAX = (1 << 63) - 1

RETURN_DELAY = 180

# wavelink 3.5: 'disabled' NO avanza la cola (bug silencioso confirmado en
# player.py:_auto_play_event). 'partial' avanza la cola pero NO genera
# recomendaciones automáticas al vaciarse - comportamiento deseado.
AUTOPLAY_MODE = wavelink.AutoPlayMode.partial


def format_duration(milliseconds):
    if not milliseconds or milliseconds <= 0 or milliseconds >= LONG_MAX:
        return "Live"
    seconds = milliseconds // 1000
    hours = seconds // 3600
    minutes = (seconds % 3600) // 60
    secs = seconds % 60
    if hours > 0:
        return f"{hours}:{minutes:02d}:{secs:02d}"
    return f"{minutes}:{secs:02d}"


def display_title(track):
    return (track.title or "").strip() or "Radio en vivo"


def decide_play_action(was_radio: bool, is_playing: bool) -> str:
    if was_radio:
        return "replace"
    if is_playing:
        return "queue"
    return "play"


class MusicCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    async def _get_player(self, interaction: discord.Interaction):
        player = interaction.guild.voice_client
        if player:
            if interaction.user.voice and player.channel != interaction.user.voice.channel:
                await player.move_to(interaction.user.voice.channel)
            return player

        if not interaction.user.voice or not interaction.user.voice.channel:
            await interaction.followup.send("Debes estar en un canal de voz.")
            return None

        player = await interaction.user.voice.channel.connect(cls=wavelink.Player, self_deaf=True)
        return player

    async def _start_autoradio(self, guild, retries=3):
        gid = guild.id
        if not autoradio_enabled.get(gid, False):
            return

        home_channel = self.bot.get_channel(config.autoradio_channel_id)
        if not home_channel:
            try:
                home_channel = await guild.fetch_channel(config.autoradio_channel_id)
            except Exception:
                pass

        if not home_channel or not isinstance(home_channel, (discord.VoiceChannel, discord.StageChannel)):
            logger.warning(f"Auto-radio channel {config.autoradio_channel_id} not found or not a voice channel")
            return

        try:
            me = guild.me
            perms = home_channel.permissions_for(me)
            if not perms.connect or not perms.speak:
                logger.warning(f"No permissions for auto-radio channel {home_channel.name}")
                return
        except Exception:
            return

        station = config.autoradio_station
        if station not in RADIO_STREAMS:
            logger.error(f"Invalid auto-radio station: {station}")
            return

        for attempt in range(retries):
            _success = False
            try:
                for vc in list(self.bot.voice_clients):
                    if vc.guild.id == gid:
                        try:
                            await vc.disconnect(force=True)
                        except Exception:
                            pass

                await asyncio.sleep(2)

                player = await home_channel.connect(cls=wavelink.Player, self_deaf=True)

                stream_url = RADIO_STREAMS[station]["url"]
                tracks = await wavelink.Pool.fetch_tracks(stream_url)
                if tracks:
                    await player.play(tracks[0], volume=player.volume)
                    _success = True
                    logger.info(f"Auto-radio started: {station} in {home_channel.name}")
                    return
                else:
                    logger.warning(f"Auto-radio: no tracks returned for {station}")
                    return
            except Exception as e:
                logger.warning(f"Auto-radio attempt {attempt + 1}/{retries} failed: {e}")
            if not _success and attempt < retries - 1:
                await asyncio.sleep(15)

        logger.error(f"Auto-radio failed after {retries} attempts for {guild.name}")

    def _schedule_return(self, guild):
        gid = guild.id
        if gid in autoradio_return_task:
            autoradio_return_task[gid].cancel()

        async def _return_after_delay():
            await asyncio.sleep(RETURN_DELAY)
            try:
                if not autoradio_enabled.get(gid, False):
                    return

                for vc in self.bot.voice_clients:
                    if vc.guild.id == gid:
                        if vc.playing or (vc.queue and not vc.queue.is_empty):
                            return
                        try:
                            await vc.disconnect(force=True)
                        except Exception:
                            pass
                        break

                await asyncio.sleep(3)

                for attempt in range(3):
                    try:
                        await self._start_autoradio(guild)
                        logger.info(f"Auto-radio returned to home channel for {guild.name}")
                        return
                    except Exception as e:
                        logger.warning(f"Auto-radio return attempt {attempt + 1} failed: {e}")
                        if attempt < 2:
                            await asyncio.sleep(15)

                logger.error("Auto-radio return failed after 3 attempts")
            except Exception as e:
                logger.error(f"Auto-radio return failed: {e}")

        autoradio_return_task[gid] = asyncio.create_task(_return_after_delay())

    def _cancel_return(self, guild):
        gid = guild.id
        task = autoradio_return_task.pop(gid, None)
        if task and not task.done():
            task.cancel()

    @commands.Cog.listener()
    async def on_wavelink_node_disconnected(self, node: wavelink.Node):
        logger.warning(f"Lavalink node disconnected: {node.uri}")
        for gid in list(autoradio_return_task.keys()):
            task = autoradio_return_task.pop(gid, None)
            if task and not task.done():
                task.cancel()

    @commands.Cog.listener()
    async def on_wavelink_node_ready(self, payload: wavelink.NodeReadyEventPayload):
        logger.info(f"Lavalink node connected: {payload.node.uri} (resumed={payload.resumed})")

    @commands.Cog.listener()
    async def on_wavelink_track_start(self, payload: wavelink.TrackStartEventPayload):
        try:
            title = getattr(payload.track, "title", "?") or "?"
            logger.info(f"Track started: {title} in {payload.player.channel} (guild {payload.player.guild.id})")
        except Exception:
            pass

    @commands.Cog.listener()
    async def on_wavelink_track_end(self, payload: wavelink.TrackEndEventPayload):
        try:
            reason = getattr(payload, "reason", "?")
            qsize = len(payload.player.queue) if payload.player and payload.player.queue else 0
            ch = getattr(payload.player.channel, "name", "?") if payload.player and payload.player.channel else "?"
            logger.info(f"Track ended: reason={reason} queue={qsize} channel={ch} guild={payload.player.guild.id if payload.player else '?'}")
        except Exception:
            pass
        player = payload.player
        if not player:
            return
        gid = player.guild.id
        home_channel_id = config.autoradio_channel_id

        if player.channel and player.channel.id == home_channel_id and autoradio_enabled.get(gid, False):
            station = config.autoradio_station
            if station in RADIO_STREAMS:
                try:
                    tracks = await wavelink.Pool.fetch_tracks(RADIO_STREAMS[station]["url"])
                    if tracks:
                        await player.play(tracks[0], volume=player.volume)
                        return
                except Exception as e:
                    logger.error(f"Auto-radio reconnect failed: {e}")
            self._schedule_return(player.guild)
            return

        if player.queue and not player.queue.is_empty:
            return

        if autoradio_enabled.get(gid, False):
            self._schedule_return(player.guild)

    @commands.Cog.listener()
    async def on_wavelink_track_exception(self, payload: wavelink.TrackExceptionEventPayload):
        player = payload.player
        if not player or not payload.track:
            return
        logger.warning(f"Track failed: {payload.track.title} - {payload.exception}")
        if player.queue and not player.queue.is_empty:
            next_track = player.queue.get()
            await player.play(next_track, volume=player.volume)

    @commands.Cog.listener()
    async def on_wavelink_track_stuck(self, payload: wavelink.TrackStuckEventPayload):
        player = payload.player
        if not player:
            return
        logger.warning(f"Track stuck: {payload.track.title} (threshold={payload.threshold})")
        if player.queue and not player.queue.is_empty:
            next_track = player.queue.get()
            await player.play(next_track, volume=player.volume)

    @commands.Cog.listener()
    async def on_wavelink_websocket_closed(self, payload: wavelink.WebsocketClosedEventPayload):
        logger.warning(f"Lavalink websocket closed: code={payload.code} reason={payload.reason}")
        if payload.code in (4014, 4006):
            for vc in list(self.bot.voice_clients):
                if vc.guild.id == payload.player.guild.id:
                    try:
                        await vc.disconnect(force=True)
                    except Exception:
                        pass
                    break

    def _check_dj(self, interaction: discord.Interaction, cmd):
        return permission_manager.has_permission(interaction.user, cmd)

    @app_commands.command(name="play", description="Reproducir una cancion")
    @app_commands.describe(query="Nombre de la cancion o URL")
    async def play(self, interaction: discord.Interaction, *, query: str):
        await interaction.response.defer()
        if not self._check_dj(interaction, "play_music"):
            await interaction.followup.send("Necesitas el rol **DJ** (o VIP) para usar este comando.")
            return
        if not interaction.user.voice or not interaction.user.voice.channel:
            await interaction.followup.send("Debes estar en un canal de voz.")
            return

        gid = interaction.guild.id
        self._cancel_return(interaction.guild)
        if gid not in autoradio_enabled:
            autoradio_enabled[gid] = True

        player_before = interaction.guild.voice_client
        was_radio = bool(
            player_before
            and player_before.channel
            and player_before.channel.id == config.autoradio_channel_id
            and autoradio_enabled.get(gid, False)
        )

        player = await self._get_player(interaction)
        if not player:
            return

        player.autoplay = AUTOPLAY_MODE

        msg = await interaction.followup.send("Buscando...")

        if not query.startswith(("http://", "https://")):
            query = f"dzsearch:{query}"

        tracks = await wavelink.Pool.fetch_tracks(query)
        if not tracks:
            await msg.edit(content="No se encontraron resultados.")
            return

        track = tracks[0]
        duration = format_duration(track.length)
        requester = interaction.user.display_name

        action = decide_play_action(was_radio, bool(player.playing))
        logger.info(f"/play decide was_radio={was_radio} is_playing={bool(player.playing)} channel_before={player_before.channel.id if player_before and player_before.channel else None} channel_after={player.channel.id if player.channel else None} action={action} query={query[:30]}")

        if action == "replace":
            if player.playing:
                await player.stop()
            player.queue.clear()
            player.queue.mode = wavelink.QueueMode.normal
            await player.play(track, volume=player.volume)

            embed = discord.Embed(
                title="Reproduciendo ahora",
                description=f"**{display_title(track)}** ({duration})",
                color=discord.Color.green()
            )
            embed.set_footer(text=f"Pedido por {requester} · la radio se reanudará al terminar")
            if track.artwork:
                embed.set_thumbnail(url=track.artwork)
            await msg.edit(content=None, embed=embed)

        elif action == "queue":
            await player.queue.put_wait(track)
            embed = discord.Embed(
                title="Anadido a la cola",
                description=f"**{display_title(track)}** ({duration})",
                color=discord.Color.blue()
            )
            embed.set_footer(text=f"Pedido por {requester} | Posicion: #{len(player.queue)}")
            await msg.edit(content=None, embed=embed)

        else:
            await player.play(track, volume=player.volume)

            embed = discord.Embed(
                title="Reproduciendo ahora",
                description=f"**{display_title(track)}** ({duration})",
                color=discord.Color.green()
            )
            embed.set_footer(text=f"Pedido por {requester}")
            if track.artwork:
                embed.set_thumbnail(url=track.artwork)
            await msg.edit(content=None, embed=embed)

    @app_commands.command(name="skip", description="Saltar cancion actual")
    async def skip(self, interaction: discord.Interaction):
        if not self._check_dj(interaction, "skip_music"):
            await interaction.response.send_message("Necesitas el rol **DJ** para usar este comando.")
            return
        player = interaction.guild.voice_client
        if not player or not player.playing:
            await interaction.response.send_message("No hay nada reproduciendose.")
            return
        await player.skip()
        await interaction.response.send_message("Cancion saltada.")

    @app_commands.command(name="stop", description="Parar musica y desconectar")
    async def stop(self, interaction: discord.Interaction):
        if not self._check_dj(interaction, "stop_music"):
            await interaction.response.send_message("Necesitas el rol **DJ** para usar este comando.")
            return
        player = interaction.guild.voice_client
        if not player:
            await interaction.response.send_message("No estoy en ningun canal de voz.")
            return
        gid = interaction.guild.id
        self._cancel_return(interaction.guild)
        autoradio_enabled[gid] = False
        await db.set_setting(f"autoradio_{gid}", "0")
        player.queue.clear()
        player.queue.mode = wavelink.QueueMode.normal
        await player.stop()
        await player.disconnect()
        await interaction.response.send_message("Bot desconectado del canal.")

    @app_commands.command(name="disconnect", description="Desconectar bot de voz")
    async def disconnect(self, interaction: discord.Interaction):
        if not self._check_dj(interaction, "disconnect_music"):
            await interaction.response.send_message("Necesitas el rol **DJ** para usar este comando.")
            return
        await self.stop(interaction)

    @app_commands.command(name="queue", description="Ver cola de reproduccion")
    async def queue_cmd(self, interaction: discord.Interaction):
        player = interaction.guild.voice_client
        if not player:
            await interaction.response.send_message("No estoy en ningun canal de voz.")
            return

        embed = discord.Embed(title="Cola de reproduccion", color=discord.Color.purple())

        if player.playing and player.current:
            current = player.current
            dur = format_duration(current.length)
            embed.add_field(
                name="Ahora",
                value=f"**{display_title(current)}** ({dur})",
                inline=False
            )

        if player.queue:
            queue_list = ""
            for i, track in enumerate(list(player.queue)[:10], 1):
                dur = format_duration(track.length)
                queue_list += f"`{i}.` **{display_title(track)}** ({dur})\n"
            if len(player.queue) > 10:
                queue_list += f"\n... y {len(player.queue) - 10} mas"
            embed.add_field(name="Proximas", value=queue_list, inline=False)
        elif not player.playing:
            embed.description = "La cola esta vacia."

        loop_str = {wavelink.QueueMode.normal: "OFF", wavelink.QueueMode.loop: "TRACK", wavelink.QueueMode.loop_all: "QUEUE"}
        vol = player.volume
        mode = loop_str.get(player.queue.mode, "OFF")
        embed.set_footer(text=f"Volumen: {vol}% | Loop: {mode}")
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="np", description="Ver cancion actual")
    async def nowplaying(self, interaction: discord.Interaction):
        player = interaction.guild.voice_client
        if not player or not player.playing:
            gid = interaction.guild.id
            home_channel_id = config.autoradio_channel_id
            if player and player.channel and player.channel.id == home_channel_id and autoradio_enabled.get(gid, False):
                station = config.autoradio_station
                info = RADIO_STREAMS.get(station, {})
                embed = discord.Embed(
                    title="Auto-Radio 24/7",
                    description=f"**{info.get('name', station)}**",
                    color=discord.Color.orange()
                )
                embed.add_field(name="Estacion", value=station, inline=True)
                embed.add_field(name="Canal", value=f"<#{home_channel_id}>", inline=True)
                await interaction.response.send_message(embed=embed)
                return
            await interaction.response.send_message("No hay nada reproduciendose.")
            return

        track = player.current
        duration = format_duration(track.length)
        embed = discord.Embed(
            title="Reproduciendo ahora",
            description=f"**{display_title(track)}** ({duration})",
            color=discord.Color.green()
        )
        embed.set_footer(text=f"Fuente: {track.source}")
        if track.artwork:
            embed.set_thumbnail(url=track.artwork)
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="volume", description="Ajustar volumen (1-200)")
    @app_commands.describe(level="Nivel de volumen (1-200)")
    async def volume(self, interaction: discord.Interaction, level: int = None):
        if not self._check_dj(interaction, "volume_music"):
            await interaction.response.send_message("Necesitas el rol **DJ** para usar este comando.")
            return
        player = interaction.guild.voice_client
        if not player:
            await interaction.response.send_message("No estoy en ningun canal de voz.")
            return

        if level is None:
            await interaction.response.send_message(f"Volumen actual: **{player.volume}%**")
            return

        if not 1 <= level <= 200:
            await interaction.response.send_message("El volumen debe ser entre 1 y 200.")
            return

        await player.set_volume(level)
        await interaction.response.send_message(f"Volumen ajustado a **{level}%**")

    @app_commands.command(name="loop", description="Alternar modo loop (off/track/cola)")
    async def loop_cmd(self, interaction: discord.Interaction):
        if not self._check_dj(interaction, "loop_music"):
            await interaction.response.send_message("Necesitas el rol **DJ** para usar este comando.")
            return
        player = interaction.guild.voice_client
        if not player:
            await interaction.response.send_message("No estoy en ningun canal de voz.")
            return

        modes = [wavelink.QueueMode.normal, wavelink.QueueMode.loop, wavelink.QueueMode.loop_all]
        current = player.queue.mode if player.queue.mode in modes else wavelink.QueueMode.normal
        idx = modes.index(current)
        next_mode = modes[(idx + 1) % len(modes)]
        player.queue.mode = next_mode

        names = {wavelink.QueueMode.normal: "OFF", wavelink.QueueMode.loop: "TRACK", wavelink.QueueMode.loop_all: "QUEUE"}
        await interaction.response.send_message(f"Loop: **{names[next_mode]}**")

    @app_commands.command(name="pause", description="Pausar reproduccion")
    async def pause(self, interaction: discord.Interaction):
        if not self._check_dj(interaction, "pause_music"):
            await interaction.response.send_message("Necesitas el rol **DJ** para usar este comando.")
            return
        player = interaction.guild.voice_client
        if not player or not player.playing:
            await interaction.response.send_message("No hay nada reproduciendose.")
            return
        await player.pause(True)
        await interaction.response.send_message("Pausado.")

    @app_commands.command(name="resume", description="Reanudar reproduccion")
    async def resume(self, interaction: discord.Interaction):
        if not self._check_dj(interaction, "resume_music"):
            await interaction.response.send_message("Necesitas el rol **DJ** para usar este comando.")
            return
        player = interaction.guild.voice_client
        if not player or not player.paused:
            await interaction.response.send_message("No hay nada pausado.")
            return
        await player.pause(False)
        await interaction.response.send_message("Reanudado.")

    @app_commands.command(name="radio", description="Iniciar radio 24/7")
    @app_commands.describe(station="Estacion (lofi, synthwave, chill, pop, rock)")
    async def radio(self, interaction: discord.Interaction, station: str = "rock"):
        await interaction.response.defer()
        if not self._check_dj(interaction, "play_radio"):
            await interaction.followup.send("Necesitas el rol **DJ** para usar este comando.")
            return
        if not interaction.user.voice or not interaction.user.voice.channel:
            await interaction.followup.send("Debes estar en un canal de voz.")
            return

        station = station.lower()
        if station not in RADIO_STREAMS:
            available = ", ".join(RADIO_STREAMS.keys())
            await interaction.followup.send(f"Estacion no valida. Opciones: `{available}`")
            return

        player = await self._get_player(interaction)
        if not player:
            return

        gid = interaction.guild.id
        self._cancel_return(interaction.guild)
        autoradio_enabled[gid] = True

        player.queue.clear()
        player.queue.mode = wavelink.QueueMode.normal

        if player.playing:
            await player.stop()

        stream_url = RADIO_STREAMS[station]["url"]
        stream_name = RADIO_STREAMS[station]["name"]

        tracks = await wavelink.Pool.fetch_tracks(stream_url)
        if not tracks:
            await interaction.followup.send("Error al cargar la estacion.")
            return

        await player.play(tracks[0], volume=player.volume)

        embed = discord.Embed(
            title="Radio 24/7 activada",
            description=f"**{stream_name}** sonando en {player.channel.mention}",
            color=discord.Color.green()
        )
        embed.add_field(name="Estacion", value=station, inline=True)
        embed.add_field(name="Comandos", value="`/radiostop` `/play` `/stop`", inline=False)
        await interaction.followup.send(embed=embed)

    @radio.autocomplete("station")
    async def station_autocomplete(self, interaction, current):
        return [
            app_commands.Choice(name=info["name"], value=key)
            for key, info in RADIO_STREAMS.items()
            if current.lower() in key.lower() or current.lower() in info["name"].lower()
        ]

    @app_commands.command(name="radiostop", description="Detener radio y auto-radio")
    async def radiostop(self, interaction: discord.Interaction):
        if not self._check_dj(interaction, "stop_music"):
            await interaction.response.send_message("Necesitas el rol **DJ** para usar este comando.")
            return
        gid = interaction.guild.id
        player = interaction.guild.voice_client

        self._cancel_return(interaction.guild)
        autoradio_enabled[gid] = False
        await db.set_setting(f"autoradio_{gid}", "0")

        if player:
            player.queue.clear()
            player.queue.mode = wavelink.QueueMode.normal
            if player.playing:
                await player.stop()
            await player.disconnect()

        await interaction.response.send_message("Radio y auto-radio detenidas. Usa `/autoradio on` para reactivar.")

    @app_commands.command(name="musiconly", description="Canal de radio: solo escuchar (ADMIN)")
    async def musiconly_cmd(self, interaction: discord.Interaction):
        if not self._check_dj(interaction, "admin_config"):
            await interaction.response.send_message("Necesitas el rol **ADMINISTRADOR** para usar este comando.")
            return

        channel = self.bot.get_channel(config.autoradio_channel_id)
        if not channel or not isinstance(channel, (discord.VoiceChannel, discord.StageChannel)):
            await interaction.response.send_message(
                f"No se encontró el canal de radio configurado (ID {config.autoradio_channel_id})."
            )
            return

        guild = interaction.guild

        listen_only = discord.PermissionOverwrite(
            view_channel=True,
            connect=True,
            speak=False,
            send_messages=False,
            read_message_history=True,
        )
        staff = discord.PermissionOverwrite(
            view_channel=True,
            connect=True,
            speak=True,
            send_messages=True,
            read_message_history=True,
        )
        bot_overwrite = discord.PermissionOverwrite(
            view_channel=True,
            connect=True,
            speak=True,
            send_messages=True,
            read_message_history=True,
        )

        applied = 0
        try:
            await channel.set_permissions(guild.default_role, overwrite=listen_only)
            applied += 1

            miembro = discord.utils.get(guild.roles, name="Miembro")
            if miembro:
                await channel.set_permissions(miembro, overwrite=listen_only)
                applied += 1

            for role_name in ("MODERADOR", "ADMINISTRADOR", "G/M", "PROPIETARIO", "🛡️ Staff Helper"):
                role = discord.utils.get(guild.roles, name=role_name)
                if role:
                    await channel.set_permissions(role, overwrite=staff)
                    applied += 1

            await channel.set_permissions(guild.me, overwrite=bot_overwrite)
            applied += 1
        except discord.Forbidden:
            await interaction.response.send_message("❌ No tengo permisos para editar los permisos de ese canal.")
            return

        logger.info(f"Music 24/7 channel set to listen-only by {interaction.user} ({applied} overwrites)")
        await interaction.response.send_message(
            f"✅ {channel.mention} configurado como **solo escuchar**:\n"
            f"• **Miembros**: pueden unirse y escuchar — sin hablar ni escribir\n"
            f"• **Staff**: puede hablar y escribir\n"
            f"• **Bot**: transmisión de radio sin restricciones\n\n"
            f"*La radio no se ve afectada: el audio del bot no depende del permiso Hablar.*"
        )

    @app_commands.command(name="autoradio", description="Configurar auto-radio (admin)")
    @app_commands.describe(action="on / off / status")
    async def autoradio(self, interaction: discord.Interaction, action: str = "status"):
        if not self._check_dj(interaction, "admin_config"):
            await interaction.response.send_message("Necesitas el rol **ADMINISTRADOR** para usar este comando.")
            return

        gid = interaction.guild.id
        action = action.lower().strip()

        if action == "on":
            await interaction.response.defer()
            autoradio_enabled[gid] = True
            await db.set_setting(f"autoradio_{gid}", "1")
            await self._start_autoradio(interaction.guild)
            station_name = RADIO_STREAMS.get(config.autoradio_station, {}).get("name", config.autoradio_station)
            embed = discord.Embed(
                title="Auto-Radio activada",
                description=f"Reproduciendo **{station_name}** en <#{config.autoradio_channel_id}>",
                color=discord.Color.green()
            )
            embed.add_field(name="Estacion", value=config.autoradio_station, inline=True)
            embed.add_field(name="Retorno", value="3 min de inactividad", inline=True)
            await interaction.followup.send(embed=embed)

        elif action == "off":
            await interaction.response.defer()
            self._cancel_return(interaction.guild)
            autoradio_enabled[gid] = False
            await db.set_setting(f"autoradio_{gid}", "0")
            player = interaction.guild.voice_client
            if player and player.channel and player.channel.id == config.autoradio_channel_id:
                player.queue.clear()
                if player.playing:
                    await player.stop()
                await player.disconnect()
            await interaction.followup.send("Auto-radio desactivada.")

        elif action == "status":
            enabled = autoradio_enabled.get(gid, False)
            station_name = RADIO_STREAMS.get(config.autoradio_station, {}).get("name", config.autoradio_station)
            embed = discord.Embed(
                title="Estado Auto-Radio",
                color=discord.Color.green() if enabled else discord.Color.red()
            )
            embed.add_field(name="Estado", value="ON" if enabled else "OFF", inline=True)
            embed.add_field(name="Estacion", value=f"{station_name} ({config.autoradio_station})", inline=True)
            embed.add_field(name="Canal", value=f"<#{config.autoradio_channel_id}>", inline=True)
            embed.add_field(name="Retorno auto", value="3 min de inactividad", inline=True)
            await interaction.response.send_message(embed=embed)

        else:
            await interaction.response.send_message("Uso: `/autoradio on` | `/autoradio off` | `/autoradio status`")

    @autoradio.autocomplete("action")
    async def autoradio_autocomplete(self, interaction, current):
        actions = [
            app_commands.Choice(name="on - Activar auto-radio", value="on"),
            app_commands.Choice(name="off - Desactivar auto-radio", value="off"),
            app_commands.Choice(name="status - Ver estado actual", value="status"),
        ]
        return [a for a in actions if current.lower() in a.value.lower()]

    async def cog_unload(self):
        for gid, task in list(autoradio_return_task.items()):
            if not task.done():
                task.cancel()
        autoradio_return_task.clear()
        autoradio_enabled.clear()
        logger.info("MusicCog unloaded, all autoradio tasks cancelled")


async def setup(bot):
    await bot.add_cog(MusicCog(bot))
