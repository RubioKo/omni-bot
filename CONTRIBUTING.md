# Contribuir a OmniBot

## Requisitos

- Python 3.12+
- [uv](https://docs.astral.sh/uv/) (package manager)
- Lavalink v4.2 (solo para probar música localmente)

## Setup

```bash
git clone https://github.com/RubioKo/omni-bot.git
cd omni-bot
uv sync --frozen --extra dev
source .venv/bin/activate   # Linux/macOS
.venv\Scripts\activate      # Windows
pre-commit install
```

## Antes de cada commit

```bash
uv run ruff check src/ tests/    # Lint
uv run pyright src/              # Type check
uv run pytest -v                 # Tests (181)
uv run python -m compileall -q src/ tests/  # Sintaxis
```

Los pre-commit hooks corren **ruff + gitleaks** automáticamente (gitleaks detecta secrets).

## Code style

- **Formatter**: ruff (line-length 120)
- **Lint rules**: E, F, W (ignorando E501)
- **No agregar comentarios** a menos que el reviewer lo pida
- Seguir los patrones existentes del codebase

## Estructura

| Directorio | Qué vive ahí |
|-----------|-------------|
| `src/cogs/` | Comandos de Discord (un cog por módulo) |
| `src/services/` | Lógica de negocio compartida |
| `src/tools/` | Herramientas de la IA (function calling) |
| `src/utils/` | Helpers genéricos |
| `src/web/` | FastAPI health check |
| `tests/` | Tests (uno por módulo) |

## Agregar un comando

1. Crear/editar el cog en `src/cogs/`
2. Usar `@app_commands.command` (solo slash commands; no hay prefijo)
3. Registrar en `bot.py` → `setup_hook()` si es cog nuevo
4. Agregar tests en `tests/`

## Pull Requests

- Ruff + pyright limpios (`uv run ruff check`, `uv run pyright`)
- Tests pasando (`uv run pytest`)
- **Nunca subas secrets, tokens, claves, IPs/dominios de producción ni IDs de servidores reales** (gitleaks en CI bloquea el PR)
- Descripción clara del cambio
- Un PR por feature/fix
- CI + Secret Scan verdes → mergeo a `main`

## Seguridad

Si encontrás una vulnerabilidad, **no abras un issue público**: seguí [`SECURITY.md`](SECURITY.md).
