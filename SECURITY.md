# Security Policy

OmniBot es código abierto (AGPL-3.0) y la seguridad es prioridad #1: el proyecto nunca debe contener secretos, tokens ni datos privados de ningún tipo.

## Supported Versions

Solo se soporta la última versión publicada en `main`. Si usás una versión anterior y encontrás una vulnerabilidad, actualizá primero y confirmá que sigue presente.

## Reporting a Vulnerability

**No abras un issue público para reportar problemas de seguridad.**

Usá el **reporte privado de vulnerabilidades** de GitHub (pestaña *Security → Report a vulnerability*) o, si el repo lo habilita, el contact del mantenedor.

Incluí en el reporte:

- Componente/comando afectado (ej: `cogs/music.py`, `/giveaway`)
- Impacto (qué puede lograr un atacante)
- Pasos de reproducción mínimos
- Fix sugerido (opcional)

El mantenedor responderá con un plan de mitigación y coordinará la divulgación responsable.

## Reglas para contribuidores

- Nunca commitees `.env`, `application.yml`, tokens, claves, IPs de producción ni IDs de servidores reales.
- Pre-commit y CI ejecutan **gitleaks** + GitHub Secret Scanning en cada push; un secret que llegue al historial se considera comprometido.
- Si detectás que se filtró un secret: avisá al mantenedor **inmediatamente** para rotarlo y purgar el historial antes de cualquier publicación.