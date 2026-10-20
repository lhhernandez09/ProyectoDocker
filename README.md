# NBA Analytics: Docker + FastAPI + PostgreSQL + Dash

Prototipo que **obtiene** partidos de la NBA desde la API pública de ESPN, los **almacena** en
PostgreSQL y los **visualiza** en un dashboard de Dash. Corre en 3 contenedores Docker.

```
API de ESPN ──► api (FastAPI · Ubuntu) ──► db (PostgreSQL) ◄── api ◄── dash (Python-Dash) ◄── navegador
```

## Arranque rápido

Requisitos: Docker Desktop iniciado (o Docker Engine con Compose v2) e Internet.

```bash
cp .env.example .env
```

```bash
docker compose up -d --build
```

```bash
docker compose ps
```

| Servicio | URL |
|---|---|
| Dashboard (Dash) | http://localhost:8050 |
| API + documentación Swagger | http://localhost:8000/docs |
| PostgreSQL (pgAdmin/DBeaver, opcional) | `127.0.0.1:5433`, base `nba`, usuario `nba_user` |

Al arrancar, la API descarga sola el catálogo de equipos. Para tener datos que graficar, en el
dashboard pulsa **Cargar temporada** (2025-26 tarda ~1.5 min) o usa el script:

```bash
docker compose exec api python -m scripts.cargar_datos temporada 2026
```

## Detener

```bash
docker compose down
```

`down` conserva los datos (volumen `pg_data`). `docker compose down -v` borra también la base.
