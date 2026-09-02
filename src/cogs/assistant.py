import asyncio
import time

import discord
from discord.ext import commands
import logging

from ..services.brain import brain
from ..services.permissions import permission_manager
from ..tools.moderation import warn_user, mute_user, unmute_user, clear_messages, set_slowmode
from ..tools.info import get_server_stats, get_user_info

logger = logging.getLogger("OmniBot.assistant")

TOOL_MAP = {
    "warn_user": warn_user,
    "mute_user": mute_user,
    "unmute_user": unmute_user,
    "clear_messages": clear_messages,
    "set_slowmode": set_slowmode,
    "get_server_stats": get_server_stats,
    "get_user_info": get_user_info,
}

TOOL_DISPLAY = {
    "warn_user": "⚠️ Advertir",
    "mute_user": "🔇 Silenciar",
    "unmute_user": "🔊 Desilenciar",
    "clear_messages": "🧹 Limpiar mensajes",
    "set_slowmode": "⏱️ Cambiar slowmode",
}

CONFIRMATION_TIMEOUT = 30
CONVERSATION_TTL = 600
CONVERSATION_MAX = 5


def build_confirmation_text(tools: list) -> str:
    lines = []
    for i, t in enumerate(tools, 1):
        name = TOOL_DISPLAY.get(t["tool"], t["tool"])
        user_str = t["params"].get("user", "")
        reason = t["params"].get("reason", "")
        duration = t["params"].get("duration", "")
        desc = f"{i}. {name} a {user_str}" if user_str else f"{i}. {name}"
        if duration:
            desc += f" por {duration}"
        if reason:
            desc += f" — {reason}"
        lines.append(desc)
    return "\n".join(lines) + "\n\n¿Confirmás?"


class MultiConfirmView(discord.ui.View):
    def __init__(self, tools, user, user_message, level_name, original_message=None):
        super().__init__(timeout=CONFIRMATION_TIMEOUT)
        self.tools = tools
        self.user = user
        self.user_message = user_message
        self.level_name = level_name
        self.original_message = original_message
        self.reply_message = None
        self._done = False

    async def _disable_buttons(self):
        for item in self.children:
            if isinstance(item, discord.ui.Button):
                item.disabled = True
        if self.reply_message:
            try:
                await self.reply_message.edit(view=self)
            except Exception:
                pass

    @discord.ui.button(label="✅ Confirmar", style=discord.ButtonStyle.green)
    async def confirm(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.user.id:
            await interaction.response.send_message(
                "Solo quien pidió la acción puede confirmar.", ephemeral=True
            )
            return
        if self._done:
            return
        self._done = True
        await interaction.response.send_message("⏳ Ejecutando...", ephemeral=True)

        results = []
        target_message = self.original_message or self.reply_message
        for t in self.tools:
            tool_name = t["tool"]
            try:
                if tool_name in TOOL_MAP:
                    result = await TOOL_MAP[tool_name](
                        interaction.client, target_message, t["params"]
                    )
                    results.append(result or "")
            except Exception as e:
                logger.error(f"Tool {tool_name} error: {e}", exc_info=True)
                results.append(f"❌ Error al ejecutar {tool_name}.")

        final = await brain.compose_response(results, self.user_message, self.level_name)
        try:
            await interaction.edit_original_response(content=final)
        except discord.HTTPException:
            pass
        self.stop()
        await self._disable_buttons()

    @discord.ui.button(label="❌ Cancelar", style=discord.ButtonStyle.red)
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.user.id:
            await interaction.response.send_message(
                "Solo quien pidió la acción puede cancelar.", ephemeral=True
            )
            return
        if self._done:
            return
        self._done = True
        await interaction.response.send_message("⏰ Acción cancelada.", ephemeral=True)
        self.stop()
        await self._disable_buttons()

    async def on_timeout(self):
        if self._done:
            return
        self._done = True
        await self._disable_buttons()


TOOL_PARAM_SCHEMAS = {
    "warn_user": {"required": ["user"], "optional": ["reason"]},
    "mute_user": {"required": ["user"], "optional": ["reason", "duration"]},
    "unmute_user": {"required": ["user"]},
    "clear_messages": {"required": [], "optional": ["count", "channel"]},
    "set_slowmode": {"required": [], "optional": ["seconds", "channel"]},
    "get_server_stats": {"required": [], "optional": []},
    "get_user_info": {"required": [], "optional": ["user"]},
}


def validate_tool_params(tool_name, params):
    schema = TOOL_PARAM_SCHEMAS.get(tool_name)
    if not schema:
        return True, ""
    for field in schema["required"]:
        if field not in params or not params[field]:
            return False, f"Falta el campo requerido: `{field}`"
    if "count" in params:
        try:
            params["count"] = min(int(params["count"]), 100)
        except (ValueError, TypeError):
            params["count"] = 10
    if "seconds" in params:
        try:
            val = int(params["seconds"])
            if val < 0 or val > 21600:
                return False, "El slowmode debe ser entre 0 y 21600 segundos."
            params["seconds"] = val
        except (ValueError, TypeError):
            return False, "Valor inválido para `seconds`."
    return True, ""


DESTRUCTIVE_TOOLS = {"warn_user", "mute_user", "clear_messages"}


class AssistantCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.conversations = {}

    def _get_history(self, user_id: int) -> list:
        now = time.time()
        entries = self.conversations.get(user_id, [])
        entries = [(ts, r, c) for ts, r, c in entries if now - ts <= CONVERSATION_TTL]
        self.conversations[user_id] = entries[-CONVERSATION_MAX:] if entries else []
        return [{"role": r, "content": c} for _, r, c in entries[-CONVERSATION_MAX:]]

    def _remember(self, user_id: int, role: str, content: str):
        content = (content or "").strip()[:200]
        if not content:
            return
        entries = self.conversations.setdefault(user_id, [])
        entries.append((time.time(), role, content))
        self.conversations[user_id] = entries[-CONVERSATION_MAX:]

    @commands.Cog.listener()
    async def on_message(self, message):
        if message.author.bot:
            return
        if message.guild is None:
            return

        mention = f"<@{self.bot.user.id}>"
        mention_nick = f"<@!{self.bot.user.id}>"
        is_mention = mention in message.content or mention_nick in message.content

        if not is_mention:
            return

        content = message.content.replace(mention, "").replace(mention_nick, "").strip()

        if not content:
            await message.reply("En que puedo ayudarte? Mencioname con tu pregunta o usa `/comandos`")
            return

        can_proceed, wait_time = permission_manager.consume_rate_limit(message.author)
        if not can_proceed:
            await message.reply(f"⏳ Estás usando el bot muy rápido. Espera {wait_time} segundos.")
            return

        user_id = message.author.id
        history = self._get_history(user_id)
        level_name = permission_manager.get_permission_name(message.author)

        logger.info(f"Message from {message.author} (Level: {level_name}): {content[:100]}")

        response = ""
        async with message.channel.typing():
            try:
                result = await asyncio.wait_for(brain.understand(content, history, level_name), timeout=65)
            except asyncio.TimeoutError:
                logger.warning(f"AI request timed out for {message.author.id}")
                await message.reply("⌛ La IA tardó demasiado en responder. Intentá de nuevo.")
                return
            tools = result.get("tools", [])
            text = result.get("text", "")

            if tools:
                denied = []
                valid_tools = []
                for t in tools:
                    tool_name = t["tool"]
                    params = t["params"]
                    if tool_name not in TOOL_MAP:
                        logger.warning(f"AI proposed unknown tool: {tool_name}")
                        continue
                    valid, err = validate_tool_params(tool_name, params)
                    if not valid:
                        logger.warning(f"Tool {tool_name} invalid params: {err}")
                        continue
                    if not permission_manager.has_permission(message.author, tool_name):
                        denied.append(permission_manager.get_required_level_name(tool_name))
                        continue
                    valid_tools.append(t)

                destructive = [t for t in valid_tools if t["tool"] in DESTRUCTIVE_TOOLS]

                if destructive:
                    confirm_text = build_confirmation_text(valid_tools)
                    if denied:
                        confirm_text += f"\n\n⚠️ Herramientas omitidas por falta de permisos: {', '.join(set(denied))}"
                    view = MultiConfirmView(valid_tools, message.author, content, level_name, original_message=message)
                    reply_msg = await message.reply(confirm_text, view=view)
                    view.reply_message = reply_msg
                    self._remember(user_id, "user", content)
                    return

                if valid_tools:
                    results = []
                    for t in valid_tools:
                        tool_name = t["tool"]
                        try:
                            r = await TOOL_MAP[tool_name](self.bot, message, t["params"])
                            results.append(r or "")
                        except Exception as e:
                            logger.error(f"Tool {tool_name} error: {e}")
                            results.append(f"❌ Error al ejecutar {tool_name}.")
                    response = await brain.compose_response(results, content, level_name)
                else:
                    response = text or (
                        f"❌ No tienes permisos para usar esas herramientas. "
                        f"Necesitas rol de {', '.join(set(denied))}."
                        if denied else "No pude determinar qué hacer."
                    )
            else:
                response = text

        if response:
            await message.reply(response)
            self._remember(user_id, "user", content)
            self._remember(user_id, "assistant", response)


async def setup(bot):
    await bot.add_cog(AssistantCog(bot))
