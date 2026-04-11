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

## Step 0 Foundation

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
  tests/
```
