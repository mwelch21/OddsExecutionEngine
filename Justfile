# Shortcuts for the local stack. The raw commands stay documented in CLAUDE.md
# and README.md — this file is convenience, not a new contract, so nothing here
# is required to work on the project.
#
# Ports come from .env when present (see .env.example). A checkout without one
# gets slot 0: api 8000, frontend 5173, postgres 5433.

set dotenv-load := true
set shell := ["bash", "-uc"]

app_port := env_var_or_default("APP_PORT", "8000")
frontend_port := env_var_or_default("FRONTEND_PORT", "5173")
postgres_host_port := env_var_or_default("POSTGRES_HOST_PORT", "5433")

alembic := "uv run alembic -c backend/db/alembic.ini"

# Show available recipes.
default:
    @just --list --unsorted

# Start api + postgres and migrate. Safe to re-run; never touches data.
up:
    docker compose up -d --wait api postgres
    docker compose exec -T api {{alembic}} upgrade head
    @echo "api  http://localhost:{{app_port}}"

# Seeding is additive and no-ops when quotes already exist, so this is as safe
# as `up`. It is a separate recipe because it is the deliberate first-run path,
# not because it is destructive.

# Cold start: up, then seed the demo fixtures.
fresh: up
    docker compose exec -T api uv run odds-db-seed-demo
    @echo "seeded"

# Backend in Docker, frontend native for fast HMR. Blocks until you stop it.
dev: up
    @echo "frontend http://localhost:{{frontend_port}} -> api http://localhost:{{app_port}}"
    cd frontend && npm install && npm run dev

# Everything in Docker, including the frontend container.
up-all:
    docker compose up -d --wait
    docker compose exec -T api {{alembic}} upgrade head

down:
    docker compose down

# Stop and delete this stack's database volume.
down-hard:
    docker compose down -v

logs service="":
    docker compose logs -f {{service}}

psql:
    docker compose exec postgres psql -U app -d odds_execution

shell:
    docker compose exec api bash

migrate:
    docker compose exec -T api {{alembic}} upgrade head

seed:
    docker compose exec -T api uv run odds-db-seed-demo

# Uses a separate database because the Postgres-gated tests drop every table in
# whatever they are pointed at.

# Full suite against the running Postgres.
test:
    #!/usr/bin/env bash
    set -euo pipefail
    port="$(docker compose port postgres 5432 | cut -d: -f2)"
    docker compose exec -T postgres psql -U app -d postgres -tc \
        "SELECT 1 FROM pg_database WHERE datname='odds_execution_test'" | grep -q 1 \
        || docker compose exec -T postgres psql -U app -d postgres -c \
            "CREATE DATABASE odds_execution_test OWNER app"
    STAGE2_TEST_DATABASE_URL="postgresql+psycopg://app:app@localhost:${port}/odds_execution_test" \
        uv run pytest

# Fast suite, no Docker. Postgres-gated tests skip.
test-quick:
    uv run pytest

lint:
    uv run ruff check .

typecheck:
    uv run mypy backend

# Everything CLAUDE.md requires before work is considered done.
check: lint typecheck test

# Truncate every application table in THIS stack. Destructive and irreversible.
reset-db:
    #!/usr/bin/env bash
    set -euo pipefail
    project="$(basename "$PWD")"
    echo "About to truncate every application table in:"
    echo "  worktree  ${PWD}"
    echo "  project   ${project}"
    echo "  postgres  localhost:{{postgres_host_port}}"
    echo
    read -r -p "Type the project name to confirm: " reply
    if [[ "$reply" != "$project" ]]; then
        echo "aborted"
        exit 1
    fi
    docker compose exec -T api uv run python -c "from backend.app.config import Settings; from backend.app.infrastructure.persistence.database import DatabaseSessionFactory; from backend.app.infrastructure.persistence.seed import truncate_application_tables; truncate_application_tables(DatabaseSessionFactory(Settings().database_url)); print('truncated')"

# Create a worktree that can run its own stack alongside this one.
worktree branch *args:
    ./scripts/new-worktree.sh {{branch}} {{args}}
