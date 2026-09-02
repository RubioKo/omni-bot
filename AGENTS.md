# AGENTS.md

Guía para **agentes de IA** y colaboradores que trabajan en **OmniBot** — bot de Discord todo-en-uno, ahora **código abierto (AGPL-3.0)**.

## Contexto

- Stack: Python 3.11–3.13 · discord.py 2.7 · SQLite async (aiosqlite) · Lavalink 4 + Wavelink 3.5 · OpenRouter (GPT-4o-mini) · FastAPI (`/health` en :8080) · uv.
- Arquitectura: cada feature es un cog (`src/cogs/`); la lógica pesada vive en `src/services/`; los "tools" de IA en `src/tools/`.
- Registrar un cog nuevo en `src/bot.py` → `setup_hook()`; los slash commands se sincronizan solos.
- Licencia AGPL-3.0: toda contribución entra bajo esa licencia.

## Reglas de oro

- **Seguridad absoluta**: NUNCA commitees secrets — ni `.env`, ni `application.yml`, ni tokens, ni claves, ni IPs/dominios de producción, ni IDs de servidores reales.
- Cualquier secret que llegue al historial se considera comprometido: gitleaks lo bloquea en pre-commit y CI; si filtra, se rota + se purga el historial.
- `main` es la rama principal; los cambios de la comunidad entran por **PR** (con CI + secret scan verdes).
- Antes de decisiones que cambien comportamiento público (env vars, comandos, DB) → documentar en `CHANGELOG.md` y `README.md`.
- CI debe quedar verde en cada push/PR: Lint (ruff + pyright + imports) · Test (3.11/3.12/3.13) · Secret Scan.

## Comandos de desarrollo

```bash
uv sync --frozen --extra dev      # instalar deps (producción + dev)
uv run pre-commit install         # hooks: ruff + trailing-whitespace + yaml + gitleaks
uv run ruff check src/ tests/     # lint
uv run pyright src/               # type check
uv run pytest -v --tb=short       # tests
uv run python -m compileall -q src/ tests/   # sintaxis
```

> **Nota pytest (solo CI/Windows):** algunos runs terminan con exit 124 por el cleanup de audioop en discord.py; el job de CI lo maneja con `timeout` y lo avisa como notice. Localmente, si colgara en Windows, usar `timeout` igual.

## Estructura clave

| Ruta | Qué es |
|------|--------|
| `src/bot.py` | Clase Bot: carga cogs, tasks 24/7, retry de Lavalink, sync de slash commands |
| `src/cogs/` | Features: assistant, automod, community, info, levels, music, roles, setup, tickets, welcome |
| `src/services/` | brain (IA), database (SQLite async), memes, modlog, permissions, rules |
| `src/tools/` | Function-calling de la IA: `info.py`, `moderation.py` |
| `src/utils/` | `members.py` (resolver), `helpers.py` (parse_duration) |
| `src/web/app.py` | FastAPI: `GET /health` (sin auth) y `/api/status` (token) |
| `tests/` | pytest; cada módulo tiene su test |

## Conventional Commits

`feat:`, `fix:`, `docs:`, `chore:`, `ci:`, `refactor:`, `security:` + descripción breve (español o inglés).

## Flujo de trabajo

1. Fork / branch desde `main`.
2. Aplicar cambios mínimos y con tests.
3. Correr lint + pyright + tests localmente.
4. PR a `main` → CI + Secret Scan.
5. Mantenedor: **@RubioKo**.

Default channel para dudas: el que figure en `README.md` (Discord/Facebook).
