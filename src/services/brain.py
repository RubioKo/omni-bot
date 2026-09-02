import json
import logging
from typing import Any
from openai import AsyncOpenAI

from ..config import config

logger = logging.getLogger("OmniBot.brain")

TOOL_DEFINITIONS = [
    {
        "type": "function",
        "function": {
            "name": "warn_user",
            "description": "Advertir a un miembro del servidor por infringir reglas",
            "parameters": {
                "type": "object",
                "properties": {
                    "user": {"type": "string", "description": "Usuario a advertir (mención o nombre)"},
                    "reason": {"type": "string", "description": "Motivo de la advertencia"}
                },
                "required": ["user", "reason"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "mute_user",
            "description": "Silenciar temporalmente a un miembro",
            "parameters": {
                "type": "object",
                "properties": {
                    "user": {"type": "string", "description": "Usuario a silenciar"},
                    "duration": {"type": "string", "description": "Duración (ej: 10m, 1h, 1d)"},
                    "reason": {"type": "string", "description": "Motivo del silencio"}
                },
                "required": ["user", "duration", "reason"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "unmute_user",
            "description": "Quitar el silencio a un miembro",
            "parameters": {
                "type": "object",
                "properties": {
                    "user": {"type": "string", "description": "Usuario a desilenciar"}
                },
                "required": ["user"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "clear_messages",
            "description": "Limpiar mensajes recientes de un canal",
            "parameters": {
                "type": "object",
                "properties": {
                    "count": {"type": "integer", "description": "Número de mensajes a eliminar (max 100)"}
                },
                "required": ["count"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "set_slowmode",
            "description": "Activar o desactivar modo lento en un canal",
            "parameters": {
                "type": "object",
                "properties": {
                    "seconds": {"type": "integer", "description": "Segundos entre mensajes (0 para desactivar)"},
                    "channel": {"type": "string", "description": "Nombre del canal (opcional, default: actual)"}
                },
                "required": ["seconds"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_server_stats",
            "description": "Obtener estadísticas del servidor de Discord (miembros, canales, roles)",
            "parameters": {"type": "object", "properties": {}}
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_user_info",
            "description": "Obtener información de un miembro de Discord",
            "parameters": {
                "type": "object",
                "properties": {
                    "user": {"type": "string", "description": "Usuario a consultar"}
                },
                "required": ["user"]
            }
        }
    },
]

SYSTEM_PROMPT = """Eres OmniBot, un bot de Discord todo-en-uno.

CONTEXTO:
- Siempre responde en español, sé conciso (máximo 3 líneas)
- El usuario que te habla tiene nivel de permiso: %%PERMISSION_LEVEL%%
- No propongas herramientas de moderación si el nivel del usuario no lo permite
- Nunca reveles información sensible del bot (tokens, API keys)
- Si no entiendes, di "No entendí, ¿puedes reformular?"
- Nunca ejecutes herramientas sin estar seguro del contexto

EJEMPLOS DE PETICIÓN → HERRAMIENTA:
1. "silencia a @usuario 10 minutos" → mute_user con user, duration 10m y reason
2. "adviértele a pepe por spam" → warn_user con user pepe y reason spam
3. "¿cuántos miembros somos?" → get_server_stats
4. "limpia 50 mensajes" → clear_messages con count 50"""

MAX_TOOLS_PER_MESSAGE = 3


class Brain:
    """Cerebro del bot - conecta con OpenRouter o usa modo básico."""

    def __init__(self):
        self.client = None
        if config.has_ai:
            self.client = AsyncOpenAI(
                base_url="https://openrouter.ai/api/v1",
                api_key=config.openrouter_api_key,
                timeout=60.0,
            )
        self.model = config.openrouter_model

    def _build_messages(self, message: str, history: list | None, permission_level: str) -> list:
        system = SYSTEM_PROMPT.replace("%%PERMISSION_LEVEL%%", permission_level)
        messages = [{"role": "system", "content": system}]
        if history:
            for entry in history[-6:]:
                messages.append({"role": entry["role"], "content": entry["content"]})
        messages.append({"role": "user", "content": message})
        return messages

    async def understand(
        self,
        message: str,
        history: list | None = None,
        permission_level: str = "MIEMBRO",
    ) -> dict[str, Any]:
        if self.client:
            result = await self._ask_ai(message, history, permission_level)
            if result.get("fallback"):
                return self._basic_match(message)
            return result
        return self._basic_match(message)

    async def _ask_ai(
        self,
        message: str,
        history: list | None,
        permission_level: str,
    ) -> dict[str, Any]:
        try:
            response = await self.client.chat.completions.create(
                model=self.model,
                messages=self._build_messages(message, history, permission_level),
                tools=TOOL_DEFINITIONS,
                tool_choice="auto",
                max_tokens=300,
                temperature=0.1,
            )
            choice = response.choices[0]
            if choice.finish_reason == "tool_calls" and choice.message.tool_calls:
                tools = []
                for tc in choice.message.tool_calls[:MAX_TOOLS_PER_MESSAGE]:
                    try:
                        args = json.loads(tc.function.arguments)
                    except json.JSONDecodeError:
                        logger.warning(f"Invalid JSON from AI: {tc.function.arguments[:200]}")
                        continue
                    tools.append({"tool": tc.function.name, "params": args})
                if len(choice.message.tool_calls) > MAX_TOOLS_PER_MESSAGE:
                    logger.warning(
                        f"AI requested {len(choice.message.tool_calls)} tools, "
                        f"executing first {MAX_TOOLS_PER_MESSAGE}"
                    )
                if tools:
                    return {"tools": tools, "text": ""}
            text = choice.message.content or ""
            return {"tools": [], "text": text.strip()}
        except Exception as e:
            logger.error(f"AI error: {e}")
            return {"fallback": True}

    async def compose_response(
        self,
        tool_results: list,
        user_message: str,
        permission_level: str = "MIEMBRO",
    ) -> str:
        if not self.client:
            return "\n".join(r for r in tool_results if r)

        results_text = "\n".join(f"- {r}" for r in tool_results if r)
        prompt = (
            "Los resultados de las herramientas ejecutadas son:\n"
            f"{results_text}\n\n"
            f"El usuario pidió: {user_message}\n"
            "Responde al usuario en español, de forma natural y concisa "
            "(máximo 3 líneas), confirmando lo que se hizo."
        )
        try:
            response = await self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {
                        "role": "system",
                        "content": SYSTEM_PROMPT.replace("%%PERMISSION_LEVEL%%", permission_level),
                    },
                    {"role": "user", "content": prompt},
                ],
                max_tokens=150,
                temperature=0.3,
            )
            text = (response.choices[0].message.content or "").strip()
            if text:
                return text
        except Exception as e:
            logger.error(f"AI compose error: {e}")
        return "\n".join(r for r in tool_results if r)

    def _basic_match(self, message: str) -> dict[str, Any]:
        import re
        msg = message.lower()
        words = set(re.findall(r"[a-záéíóúñ]+", msg))
        if {"warn", "warnear", "advertir", "advierte", "advertencia"} & words:
            return {"tools": [{"tool": "warn_user", "params": {"user": self._extract_user(msg), "reason": msg}}], "text": ""}
        if {"mute", "mutear", "silenciar", "silencio"} & words:
            return {"tools": [{"tool": "mute_user", "params": {"user": self._extract_user(msg), "duration": "10m", "reason": msg}}], "text": ""}
        if {"stats", "estadisticas", "estadísticas", "miembros"} & words:
            return {"tools": [{"tool": "get_server_stats", "params": {}}], "text": ""}
        return {"tools": [], "text": "No entendí. Puedes probar: warn, mute, stats"}

    def _extract_user(self, msg: str) -> str:
        import re
        match = re.search(r'<@!?(\d+)>', msg)
        return match.group(0) if match else "usuario"

brain = Brain()
