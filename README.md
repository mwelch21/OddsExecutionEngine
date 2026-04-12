# OddsExecutionEngine

A backend system for evaluating fillability and executing best available odds across fragmented sportsbook markets.

## Overview

This project simulates a real-time market execution system:
- Cross-book odds comparison
- Fillability evaluation
- Best execution selection
- Monitoring and opportunity detection

Built with a focus on:
- Deterministic logic
- Event-driven architecture
- Extensible system design
- Structured service-level logging for request and workflow visibility

## Stage 3 Event Layer

The repository now includes the stage 3 event boundary for the recommendation workflow:
- explicit domain workflow events
- persisted `workflow_events` audit/outbox rows
- synchronous post-commit publishing through infrastructure adapters

## Stage 2 Enhanced Foundation

The repository now includes a minimal FastAPI backend, Docker-based Postgres, and baseline lint/type/test tooling.

### Prerequisites

- Python 3.12
- `uv`
- Docker Desktop

### First Run

Install local dependencies:

```bash
uv sync --group dev
```

Run the test and quality checks locally:

```bash
uv run pytest
uv run ruff check .
uv run mypy backend
```

Or run them inside the API container:

```bash
docker compose exec api uv run pytest
docker compose exec api uv run ruff check .
docker compose exec api uv run mypy backend
```

Start the full local stack with Docker Compose:

```bash
docker compose up --build
```

The API will be available at `http://localhost:8000`, and the health endpoint is:

```text
GET /health
```

Postgres is available to the API on the internal Docker network at `postgres:5432`. It is not exposed to your host by default, which avoids conflicts with any local Postgres instance already using port `5432`.

## Database Workflow

Schema changes are managed through versioned migrations in `backend/db/migrations`. The app does not create tables on startup.

Recommended local sequence:

1. Start containers:

```bash
docker compose up --build -d
```

2. Run migrations from inside the API container:

```bash
docker compose exec -T api uv run alembic -c backend/db/alembic.ini upgrade head
```

3. Optionally seed demo quotes from inside the API container:

```bash
docker compose exec -T api uv run odds-db-seed-demo
```

4. Run the app or tests:

```bash
docker compose exec -T api uv run pytest
```

5. Inspect data with `psql`:

```bash
docker compose exec postgres psql -U app -d odds_execution
```

SQLite is kept only for lightweight local smoke/convenience coverage in tests. Postgres is the required persistence truth path.

If you want to run migration or seed commands directly on your host instead of inside the API container, you must point them at a reachable Postgres instance first. The default settings use `postgres:5432`, which is only resolvable on the Docker network.

Example host-side override:

```bash
POSTGRES_HOST=localhost POSTGRES_PORT=5432 uv run alembic -c backend/db/alembic.ini upgrade head
POSTGRES_HOST=localhost POSTGRES_PORT=5432 uv run odds-db-seed-demo
```

Those host-side commands require Postgres to be exposed to your host, or an equivalent reachable DB hostname.

## Verification Script

Run the current end-to-end manual verification flow with:

```bash
./scripts/verify_stage2_5.sh
```

The script:
- starts the local stack
- runs migrations
- seeds demo quotes
- verifies health and recommendation endpoint behavior
- checks validation failures
- verifies persisted row counts in Postgres

Architecture decisions and standing implementation rules live in:

- `docs/architecture/decisions.md`
- `docs/architecture/conventions.md`

### Environment

Copy `.env.example` to `.env` if you want local overrides. Keep `.env` uncommitted and treat environment variables as the source of truth for production deployment.

For security:
- never commit real secrets
- use a unique `POSTGRES_PASSWORD` in production
- `production` will fail startup if `POSTGRES_PASSWORD` is left at a known default value

### Postgres Persistence

Postgres uses the named Docker volume `postgres_data`, so data survives normal container shutdowns and `docker compose down`.

Data is removed only if you explicitly delete the volume, for example:

```bash
docker compose down -v
```

### Project Layout

```text
backend/
  app/
    main.py
    config.py
    api/
    domain/
    application/
    engines/
    infrastructure/
  db/
    migrations/
  tests/
```
