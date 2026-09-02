# Changelog

El formato se basa en [Keep a Changelog](https://keepachangelog.com/).

## [1.0.0] - 2026-09-01

### Added

- **Open source (AGPL-3.0)**: `LICENSE` con el texto canónico.
- `SECURITY.md`: política de seguridad + reporte privado de vulnerabilidades.
- `CODE_OF_CONDUCT.md` (Contributor Covenant 2.1).
- Job de **Secret Scan (gitleaks v8.30.1)** en CI (`.github/workflows/secret-scan.yml`), que escanea el historial completo en cada push/PR.
- Hook local de **gitleaks** en `.pre-commit-config.yaml`.
- Endurecido `.gitignore`: `.env.*`, `lavalink/`, `*.jar`, `*.keystore`, `*.sqlite`, `*.sqlite3`.
- README: sección **Contribuir/Community**, guía para asistentes de IA (`AGENTS.md`) y badges de licencia.
- `AGENTS.md` expandida para colaboradores y agentes de IA.

### Changed

- Proyecto pasa de **privado/comercial** a **código abierto**: remoto origin pasará a `RubioKo/omni-bot`.
- `pyproject.toml`: `license` → `AGPL-3.0-only` (SPDX).
- README: eliminado lenguaje "private/proprietary".

## [2.4.2] - 2026-08-28

### Changed

- Actualizado `aiosqlite` 0.21.0 → 0.22.1 (Connection ya no hereda de `threading.Thread`; `close_db()` ya usa `await close()`)
- Actualizado `PyNaCl` 1.5.0 → 1.6.2
- Actualizado GitHub Actions a Node 24: `actions/checkout` v7.0.1, `actions/setup-python` v7.0.0, `astral-sh/setup-uv` v10.0.1 y `codecov/codecov-action` v7.0.0 (SHA pinneados)
- Regenerado `requirements.txt`/`uv.lock` con `uv export`/`uv lock`
- `pydantic-core` se mantiene en 2.46.4 (versión exacta requerida por `pydantic==2.13.4`; el bump de Dependabot a 2.48.0 era inválido)

## [2.4.1] - 2026-08-28

### Changed

- Actualización a `pytest==8.4.2`, `pytest-asyncio==1.4.0` y `pytest-cov==7.1.0`
- Eliminado `asyncio_mode = "auto"` (removido en pytest-asyncio 1.x) → tests async ahora usan `@pytest.mark.asyncio` explícito
- Eliminado `pytest.ini` obsoleto (config ya en `pyproject.toml`)
- `nixpacks.toml`: uv instalado con curl (en vez de `pip install uv`, inexistente en el contenedor nix)

## [2.4.0] - 2026-08-26

### Added

- uv package manager (`uv.lock`, `pyproject.toml` PEP 621)
- FastAPI health check endpoint (`/health`, `/api/status` en :8080)
- pyright type checking (CI + incremental hints en config/database)
- Pre-commit hooks (ruff, trailing-whitespace, end-of-file, yaml, large files)
- GitHub issue templates (bug report, feature request)
- GitHub PR template
- CODEOWNERS (@RubioKo)
- CONTRIBUTING.md
- `py.typed` PEP 561 marker
- `HEALTH_CHECK_PORT` env var (default: 8080)
- `LOG_FILE` env var para RotatingFileHandler (opcional)
- Dependabot para actualizaciones automáticas de deps

### Changed

- **CI/CD**: split lint → test jobs, SHA-pinned actions, matrix Python 3.11/3.12/3.13
- **CI/CD**: `uv sync --frozen --extra dev` reemplaza `pip install`
- **Logging**: `logging.basicConfig()` → `dictConfig` + `RotatingFileHandler` opcional
- **nixpacks.toml**: health check ahora usa FastAPI `/health` (antes Lavalink auth)
- **README**: tests 184 → 199, instrucciones uv, health check FastAPI, estructura actualizada
- **pyproject.toml**: versión 2.3.0 → 2.4.0

### Fixed

- CI hang en Python 3.12 (audioop non-daemon threads → pytest timeout + exit code 124)
- autoradio hybrid command defer bug en VPS

## [2.3.0] - 2026-08-XX

### Added

- Complete moderation suite (word filter, mass-ping, caps, emoji spam, auto-lockdown)
- Ticket system (panel + modal + transcript)
- AI conversation memory (5 turns, 10min TTL)
- Multi-tool support (max 3 per message)
- Meme feedback adaptativo + weekly winner
- Themed days (gaming, dark, futbol)
- Memes quantity parameter (1-3)
- MemeRerollView with rate limiting

### Changed

- AI brain overhaul (brain.compose_response, few-shot prompt)
- Meme pipeline: Reddit RSS + meme-api + EN fallback
- Unified member resolver (mention > exact > prefix > substring)

### Fixed

- `html.unescape` RSS double-encoded ampersands
- Whitelist image handling
- Hotlink hostile domain detection
