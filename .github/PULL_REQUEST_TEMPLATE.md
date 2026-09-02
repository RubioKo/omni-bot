## Descripción

Describí el cambio que hacés y por qué.

- Closes #_(si aplica, linkeá el issue)_

## Tipo de cambio

- [ ] Bug fix
- [ ] Nuevo feature
- [ ] Refactor
- [ ] Docs
- [ ] CI/CD / Seguridad

## Cómo lo probé

- [ ] `uv run ruff check src/ tests/` pasa
- [ ] `uv run pyright src/` pasa
- [ ] `uv run pytest -v` pasa (181 tests)
- [ ] `pre-commit` pasa (incluye gitleaks)

## Checklist de open source

- [ ] No se agregaron **secrets, tokens, claves o IPs/dominios de producción**
- [ ] Documentación actualizada en `README.md` / `CHANGELOG.md` (si aplica)
- [ ] No rompe compatibilidad con env vars / comandos / DB (si lo hace, documentado)
- [ ] Comportamiento verificable (tests o pasos de prueba)
