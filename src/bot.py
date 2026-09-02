import asyncio
import time

import discord
from discord.ext import commands, tasks
import logging
from datetime import datetime
import wavelink
from .config import config

logger = logging.getLogger("OmniBot.bot")

intents = discord.Intents.default()
intents.message_content = True
intents.members = True
intents.voice_states = True

class OmniBot(commands.Bot):
    def __init__(self):
        super().__init__(
            command_prefix=[],
            intents=intents,
            description="OmniBot Assistant",
        )
        self.config = config
        self._ready_done = False
        self._lavalink_ready = False
        self._last_meme_slot = None
        self._task_errors = {}
        self._web_server = None
        self._web_server_task = None

    async def close(self):
        from .services import database
        if self._web_server is not None:
            self._web_server.should_exit = True
        if self._web_server_task is not None:
            try:
                await asyncio.wait_for(self._web_server_task, timeout=5)
            except Exception:
                logger.warning("Web server task did not exit cleanly on shutdown")
        await database.close_db()
        await super().close()

    async def setup_hook(self):
        from .services import database
        await database.init_db()
        from .cogs.roles import RoleView
        self.add_view(RoleView())
        for ext in [
            "src.cogs.assistant",
            "src.cogs.welcome",
            "src.cogs.setup",
            "src.cogs.music",
            "src.cogs.automod",
            "src.cogs.levels",
            "src.cogs.info",
            "src.cogs.community",
            "src.cogs.tickets",
        ]:
            try:
                await self.load_extension(ext)
            except Exception as e:
                logger.error(f"Failed to load {ext}: {e}", exc_info=True)

        from .cogs.tickets import TicketView
        self.add_view(TicketView())
        from .services.memes import MemeRerollView
        self.add_view(MemeRerollView())

        for attempt in range(3):
            try:
                nodes = [wavelink.Node(uri=config.lavalink_uri, password=config.lavalink_password)]
                await wavelink.Pool.connect(nodes=nodes, client=self)
                self._lavalink_ready = True
                logger.info("Lavalink node connected")
                break
            except Exception as e:
                logger.error(f"Lavalink connection attempt {attempt + 1} failed: {e}")
                if attempt < 2:
                    await asyncio.sleep(5)

        self.daily_meme.start()
        self.db_backup.start()
        logger.info("All cogs and Lavalink node loaded")

        try:
            synced = await self.tree.sync()
            logger.info(f"Slash commands synced: {len(synced)}")
        except Exception as e:
            logger.error(f"Failed to sync slash commands: {e}")

        import uvicorn
        from .web.app import app
        uvicorn_config = uvicorn.Config(
            app,
            host="0.0.0.0",
            port=config.health_check_port,
            log_level="warning",
        )
        self._web_server = uvicorn.Server(uvicorn_config)
        self._web_server_task = asyncio.create_task(self._web_server.serve())
        self._web_server_task.add_done_callback(self._on_web_server_done)

    def _on_web_server_done(self, task: asyncio.Task):
        try:
            task.result()
        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.error(f"Web server crashed: {e}", exc_info=True)

    async def report_task_error(self, task_name: str, error: Exception):
        now = time.time()
        errors = self._task_errors.setdefault(task_name, [])
        errors = [t for t in errors if now - t < 3600]
        errors.append(now)
        self._task_errors[task_name] = errors

        if len(errors) < 3:
            return

        self._task_errors[task_name] = []
        err_type = type(error).__name__
        err_msg = str(error)[:200].replace("`", "'")
        logger.error(f"Task {task_name} failed 3+ times in the last hour, alerting owner")
        seen_owners = set()
        for guild in self.guilds:
            owner = guild.owner
            if not owner or owner.id in seen_owners:
                continue
            seen_owners.add(owner.id)
            try:
                await owner.send(
                    f"⚠️ **OmniBot alerta**: la tarea `{task_name}` falló 3+ veces "
                    f"en la última hora.\nÚltimo error: `{err_type}: {err_msg}`\nRevisa los logs de Dokploy."
                )
            except discord.Forbidden:
                pass

    @tasks.loop(hours=24)
    async def db_backup(self):
        from .services import database
        try:
            path = await database.backup_database()
            if path:
                removed = await database.prune_backups(config.backup_retention_days)
                logger.info(f"Database backup created: {path} (pruned {removed} old)")
        except Exception as e:
            logger.error(f"Backup task error: {e}", exc_info=True)
            await self.report_task_error("db_backup", e)

    @db_backup.before_loop
    async def before_db_backup(self):
        await self.wait_until_ready()

    async def on_ready(self):
        logger.info(f"Bot connected as {self.user} ({self.user.id})")
        logger.info(f"Guilds: {len(self.guilds)}")
        await self.change_presence(activity=discord.Game(name="OmniBot"))

        if self._ready_done:
            return
        self._ready_done = True

        await self._start_autoradio_on_boot()

    async def _start_autoradio_on_boot(self):
        await asyncio.sleep(3)
        music_cog = self.get_cog("MusicCog")
        if not music_cog or not self._lavalink_ready:
            return
        from .cogs.music import autoradio_enabled
        from .services import database
        try:
            last_slot = await database.get_setting("meme_last_slot")
            self._last_meme_slot = last_slot
        except Exception:
            pass
        for guild in self.guilds:
            try:
                state = await database.get_setting(f"autoradio_{guild.id}")
                if state is None:
                    autoradio_enabled[guild.id] = True
                else:
                    autoradio_enabled[guild.id] = state == "1"
                await music_cog._start_autoradio(guild)
            except Exception as e:
                logger.error(f"Auto-radio failed for {guild.name}: {e}")

    @tasks.loop(minutes=30)
    async def daily_meme(self):
        try:
            from zoneinfo import ZoneInfo
            from .services.memes import (
                get_daily_meme,
                get_theme_for_weekday,
                send_meme,
                MemeRerollView,
            )
            from .services import database

            tz = ZoneInfo(config.meme_timezone)
            now = datetime.now(tz)
            hours = []
            for h in config.meme_hours.split(","):
                h = h.strip()
                if not h:
                    continue
                try:
                    hours.append(int(h))
                except ValueError:
                    logger.warning(f"MEME_HOURS inválido: '{h}' ignorado")
            if not hours or now.hour not in hours:
                return

            slot = f"{now.date().isoformat()}-{now.hour}"
            if slot == self._last_meme_slot:
                return

            is_weekly_slot = now.weekday() == 0 and now.hour == hours[0]

            if is_weekly_slot:
                await self._post_weekly_winner()

            theme = get_theme_for_weekday(now.weekday())
            meme = await get_daily_meme(theme)

            if not meme:
                logger.warning("No meme found for this slot")
                return

            for guild in self.guilds:
                channel = discord.utils.get(guild.text_channels, name="memes")
                if not channel:
                    continue
                try:
                    await send_meme(channel, meme, MemeRerollView())
                    logger.info(f"Meme posted in {guild.name}/#memes")
                except Exception as e:
                    logger.error(f"Error posting meme in {guild.name}: {e}")

            self._last_meme_slot = slot
            await database.set_setting("meme_last_slot", slot)
            await database.prune_meme_history(30)
        except Exception as e:
            logger.error(f"Daily meme task error: {e}", exc_info=True)
            await self.report_task_error("daily_meme", e)

    async def _post_weekly_winner(self):
        from .services import database
        try:
            winner = await database.get_weekly_winner(7)
            if not winner:
                logger.info("Weekly meme skipped: no feedback data yet")
                return

            from .services.memes import prepare_memes

            for guild in self.guilds:
                channel = discord.utils.get(guild.text_channels, name="memes")
                if not channel:
                    continue
                try:
                    embeds, files = await prepare_memes([{
                        "title": winner["title"] or "El meme más reaccionado de la semana",
                        "url": winner["url"],
                        "permalink": None,
                        "subreddit": winner["source"],
                        "upvotes": winner["reactions"],
                        "is_video": False,
                    }])
                    if not embeds:
                        continue
                    embed = embeds[0]
                    embed.title = "🏆 MEME DE LA SEMANA"
                    embed.set_footer(text=f"😂 {winner['reactions']} reacciones esta semana")
                    kwargs = {"embed": embed}
                    if files:
                        kwargs["files"] = files
                    await channel.send(**kwargs)
                except Exception as e:
                    logger.error(f"Error posting weekly meme in {guild.name}: {e}")
            logger.info(f"Weekly meme winner posted ({winner['reactions']} reactions)")
        except Exception as e:
            logger.error(f"Weekly meme task error: {e}", exc_info=True)
            await self.report_task_error("weekly_meme", e)

    @daily_meme.before_loop
    async def before_daily_meme(self):
        await self.wait_until_ready()

    async def on_app_command_error(self, interaction: discord.Interaction, error: discord.app_commands.AppCommandError):
        original = getattr(error, "original", error)
        command_name = getattr(getattr(interaction, "command", None), "qualified_name", None) or "desconocido"
        if isinstance(original, discord.NotFound):
            logger.warning(f"App command interaction expired: {command_name}")
            return
        if isinstance(original, discord.app_commands.MissingPermissions):
            try:
                await interaction.response.send_message("No tienes permisos para usar este comando.", ephemeral=True)
            except discord.InteractionResponded:
                pass
            return
        if isinstance(original, discord.app_commands.CheckFailure):
            try:
                await interaction.response.send_message("No tienes permisos para usar este comando.", ephemeral=True)
            except discord.InteractionResponded:
                pass
            return

        logger.error(f"App command error in {command_name}: {error}", exc_info=error)
        try:
            if interaction.response.is_done():
                await interaction.followup.send(
                    f"Ocurrió un error al ejecutar `{command_name}`. Revisa los logs.",
                    ephemeral=True,
                )
            else:
                await interaction.response.send_message(
                    f"Ocurrió un error al ejecutar `{command_name}`. Revisa los logs.",
                    ephemeral=True,
                )
        except Exception:
            logger.error("on_app_command_error: no se pudo enviar el mensaje de error (interaccion expirada)")

bot = OmniBot()
