# OddsExecutionEngine

A sports market execution platform that evaluates fillability and identifies best-available odds across fragmented sportsbook markets. Submit an order intent with target odds, and the system finds matching quotes, recommends whether the order is fillable, and monitors markets for favorable opportunities.

## What It Does

- **Cross-book odds comparison** -- Ingests quotes from multiple sportsbooks (DraftKings, FanDuel, BetMGM, etc.) and normalizes them into a unified market view
- **Fillability evaluation** -- Given a target price, determines whether any sportsbook can fill the order and ranks all matching quotes
- **Watch intents & opportunity detection** -- Set a target price on a market and the system continuously evaluates incoming quotes, creating immutable opportunity snapshots when a fillable match is found
- **Live data integration** -- Connects to [The Odds API](https://the-odds-api.com) for real-time sportsbook odds across NHL, MLB, and other sports
- **Event-driven architecture** -- All state changes produce domain events, persisted atomically alongside business data

## Architecture

Strict layered architecture with one-way dependency arrows:

```
api/ --> application/ --> domain/         (pure, zero external imports)
                      --> engines/        (pure functions, zero I/O)
                      --> infrastructure/ (DB, HTTP providers, publishers)
```

**Key design principles:**

- **Deterministic engines** -- All matching, comparison, and evaluation logic lives in pure functions. Same input = same output. No I/O ever.
- **Immutable domain models** -- Frozen Pydantic models (`extra="forbid"`). Value objects, not entities.
- **Unit of Work + staged events** -- Events are staged during a workflow, persisted in the same DB transaction as business data, and published only after successful commit. Rollback discards everything.
- **Ports & adapters** -- Application layer depends on Protocol interfaces. Infrastructure implements them. Swap providers without touching business logic.

**Architecture docs:**

- `docs/architecture/system-state-data-flow.md` -- current end-to-end architecture, state ownership, bottlenecks, and scale considerations
- `docs/architecture/stages-5-6-data-flows.md` -- detailed watch/opportunity and live-ingestion flow walkthrough

## Prerequisites

To run OddsCafe in containers, the host needs Git to clone the repo and a running Docker installation with Buildx and the Compose plugin (`docker compose`). Docker Desktop or Docker Engine with those plugins works. The `just` command runner is optional.

| Service | What the container supplies | When you need tools on the host |
|---|---|---|
| API and auto-refresh worker | Python 3.12, uv, backend packages and test tools | For native debugging, linting or tests, install Python 3.12.x and uv, then run `uv sync --locked --group dev`. |
| Frontend | Node 22, npm and the React/Vite packages | For native Vite, including `just dev`, install Node 22.20+ on the 22.x line and npm, then run `npm ci` in `frontend/`. |
| PostgreSQL | PostgreSQL 16 server and the `psql` client | Use `docker compose exec postgres psql -U app -d odds_execution` for a database shell. A host database install is unnecessary. |
| Web Push notifier | Go 1.26 build stage and a runtime image containing the compiled notifier | For native notifier development or `just test-notifier`, install Go 1.26.1 or later. |

## Getting Started

Clone the repository and run these commands from its root. Compose defaults support fixture data without credentials or a local `.env` file.

```bash
git clone https://github.com/mwelch21/OddsExecutionEngine.git
cd OddsExecutionEngine

docker compose up --build -d --wait postgres api
docker compose exec -T api uv run odds-db-upgrade
docker compose exec -T api uv run odds-db-seed-demo
docker compose up --build -d auto-refresh frontend
```

Open the [frontend](http://localhost:5173), [API health check](http://localhost:8000/api/health) or [development testing dashboard](http://localhost:8000/api/v1/test-ui). Use `docker compose down` to stop the stack and retain its database volume.

### Optional configuration

For custom ports or provider settings, create a root `.env` from `.env.example` on first setup. Containers reach the database at `postgres:5432`. Native backend commands use `POSTGRES_HOST=localhost` and `POSTGRES_PORT` equal to the published `POSTGRES_HOST_PORT` (default `5433`).

For live quotes, set `QUOTE_PROVIDER=odds_api` and supply `ODDS_API_KEY`. For browser notifications, configure VAPID and then start the notifier with `docker compose up --build -d notifier`. See the [Web Push runbook](docs/runbooks/web-push.md).

### Optional Ubuntu workstation bootstrap

On Ubuntu 24.04 LTS x86_64, run `./scripts/bootstrap.sh` from the clone to install the host development tools and sync all three native environments. Run it as your development user. System package installation and Docker group setup use sudo. If group membership changes, start a new login session.

Rerun bootstrap after dependency changes. It preserves existing `.env` settings. Use `./scripts/doctor.sh` to check workstation prerequisites and service status. Sign in with `claude`, `codex login --device-auth` or `gh auth login` only for the developer tools you use. The [dependency inventory](docs/development-dependencies.md) covers installer maintenance and supported versions.

## Local Development Loop

For backend reload and native Vite, install `just`, Node.js and npm on the host. These recipes also start the notifier, which needs Web Push configuration for delivery.

```bash
just fresh   # first run only: refresh + seed the demo fixtures
just dev     # every session, and after every pull or branch switch
```

`just dev` runs `just refresh` first, so the API is rebuilt, recreated, and migrated
for the checked-out branch before Vite starts. Local data is never touched.

### What reloads on its own, and what does not

| You changed | Picked up by | You run |
|---|---|---|
| Frontend source | Vite HMR | nothing |
| Backend source (`backend/`) | uvicorn `--reload` (source is mounted in dev mode) | nothing |
| Backend source, for the Auto-Refresh worker | mounted, but no reloader | `just refresh` (restarts the worker) |
| `pyproject.toml`, `Dockerfile` | image rebuild | `just refresh` |
| A new migration | Alembic | `just refresh` (or `just migrate`) |
| `frontend/package.json` | `npm install` | restart `just dev` |
| Branch (pull, switch, new worktree) | all of the above | `just refresh` / `just dev` |

`just status` reports whether the running stack matches the checkout (reload on,
image built from this `pyproject.toml`, schema at head) and exits non-zero when it
does not.

### Dev mode vs image mode

| Recipe | API runs | Use for |
|---|---|---|
| `just up`, `just refresh`, `just dev`, `just up-all` | mounted `backend/`, reload on save | day-to-day work |
| `just up-image`, raw `docker compose up` | the built image as-is, no reload | production-like checks |

Dev mode is `docker-compose.dev.yml` layered over `docker-compose.yml`; the image and
the base compose file are unchanged. Destructive resets stay explicit:
`just down-hard` (asks first) deletes the volume, `just reset-db` truncates tables.

## Common Commands

Run backend tools inside the running API container:

```bash
docker compose exec -T api uv run pytest
docker compose exec -T api uv run ruff check .
docker compose exec -T api uv run mypy backend
docker compose logs -f api
```

For native debugging, sync the Python environment and configure the host database connection as described above, then run:

```bash
docker compose stop api
uv run uvicorn backend.app.main:create_app --factory --reload --port 8000
```

With native tools installed, `just check` runs Ruff, mypy and PostgreSQL-backed pytest. `just test-notifier` runs the Go integration suite. Both use the dedicated `odds_execution_test` database with the default development credentials. Reserve this database for tests because the suite resets its tables. Build the frontend with `npm run build` from `frontend/`. See the [testing guide](docs/testing/README.md).

## API Endpoints

Every route is served under `/api/v1`; only the health probe sits outside the version, at `/api/health` (ADR-018). An additive change keeps `v1`; a breaking change adds `/api/v2` beside it.

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/api/health` | Health check (unversioned ops probe) |
| `POST` | `/api/v1/execution/recommendation` | Evaluate fillability for an order intent |
| `POST` | `/api/v1/ingestion/quotes/refresh` | Refresh quotes for a single event |
| `POST` | `/api/v1/ingestion/quotes/refresh-sport` | Refresh all events for a sport (live data) |
| `GET` | `/api/v1/events?league=&sport=&page=&page_size=` | Browse upcoming events with quote freshness |
| `GET` | `/api/v1/events/{id}/quotes` | One event's line board: markets, books ranked best-first |
| `POST` | `/api/v1/watch-intents` | Create a watch intent (monitors for target price) |
| `GET` | `/api/v1/watch-intents?event_id=` | List active watch intents |
| `DELETE` | `/api/v1/watch-intents/{id}` | Cancel a watch intent |
| `GET` | `/api/v1/opportunities?event_id=` | List opportunities with computed validity |
| `GET` | `/api/v1/admin/auto-refresh` | Auto-Refresh switch, interval, warn-below floor and last refresh outcome (operator) |
| `PUT` | `/api/v1/admin/auto-refresh` | Turn Auto-Refresh on or off, set the interval (1-60 min) and floor (operator) |
| `GET` | `/api/v1/test-ui` | Interactive testing dashboard (dev only) |

### Example: Get a recommendation

```bash
curl -X POST http://localhost:8000/api/v1/execution/recommendation \
  -H 'Content-Type: application/json' \
  -d '{
    "event_id": "nba-knicks-celtics-2026-04-11",
    "market_type": "moneyline",
    "selection": "knicks",
    "target_price": 121
  }'
```

### Example: Refresh live NHL odds

```bash
curl -X POST http://localhost:8000/api/v1/ingestion/quotes/refresh-sport \
  -H 'Content-Type: application/json' \
  -d '{"sport": "icehockey_nhl"}'
```

### Example: Create a watch intent

```bash
curl -X POST http://localhost:8000/api/v1/watch-intents \
  -H 'Content-Type: application/json' \
  -d '{
    "event_id": "EVENT_ID_FROM_REFRESH",
    "market_type": "moneyline",
    "selection": "boston bruins",
    "target_price": -140
  }'
```

### Request validation rules

- `moneyline` -- `line` must be absent or null
- `spread` / `total` -- `line` is required
- `total` -- `selection` must be `"over"` or `"under"`

## Project Structure

```
backend/
├── app/
│   ├── main.py                          # App factory, middleware, DI wiring
│   ├── config.py                        # pydantic-settings, env vars
│   ├── api/                             # Routers + request/response schemas
│   ├── domain/
│   │   ├── models.py                    # Immutable value objects
│   │   └── events.py                    # 8 domain event types
│   ├── application/
│   │   ├── ports.py                     # Protocol interfaces
│   │   ├── recommendation_service.py
│   │   ├── quote_ingestion_service.py
│   │   └── watch_intent_service.py
│   ├── engines/                         # Pure deterministic logic (NO I/O)
│   │   ├── normalization_engine.py
│   │   ├── quote_matching_engine.py
│   │   ├── price_comparison_engine.py
│   │   ├── recommendation_engine.py
│   │   ├── watch_evaluation_engine.py
│   │   └── opportunity_validity_engine.py
│   └── infrastructure/
│       ├── quote_provider.py            # InMemoryQuoteProvider (fixtures)
│       ├── odds_api_provider.py         # TheOddsApiProvider (live data)
│       ├── publishers/                  # Event publishers
│       ├── observability/               # Structured logging
│       └── persistence/                 # DB session, schema, UoWs, migrations
├── db/
│   └── migrations/                      # Alembic migrations
└── tests/                               # Unit + integration tests
```

frontend/
├── src/
│   ├── App.tsx                         # Single-page lines/watch UI
│   ├── components/                      # Lightweight UI primitives + feature panels
│   ├── lib/                             # API client and demo line fixtures
│   └── styles.css                       # Design tokens and layout primitives
├── vite.config.ts                       # Dev proxy to FastAPI
└── package.json
```

## Database

10 tables managed via Alembic migrations:

`events`, `event_participants`, `markets`, `market_quotes_latest`, `market_quotes_history`, `order_intents`, `execution_recommendations`, `workflow_events`, `watch_intents`, `opportunities`

### Resetting the database

```bash
docker compose down -v        # removes the volume (all data lost)
docker compose up -d
uv run odds-db-upgrade
uv run odds-db-seed-demo
```

## Configuration Reference

All three host ports are configurable so two worktrees can run their stacks at
the same time. The defaults are "slot 0" — the values this repo has always used —
so a checkout with no `.env` behaves exactly as before. See
[docs/development/worktrees.md](docs/development/worktrees.md).

| Variable | Default | Description |
|----------|---------|-------------|
| `APP_ENV` | `development` | `production` enforces security constraints |
| `POSTGRES_DB` | `odds_execution` | Database name |
| `POSTGRES_USER` | `app` | Database user |
| `POSTGRES_PASSWORD` | `app` | Database password (must change in production) |
| `POSTGRES_HOST` | `postgres` | `localhost` when running outside Docker |
| `POSTGRES_PORT` | `5432` | Port inside the container; unchanged by the host mapping |
| `APP_PORT` | `8000` | Host port the API binds |
| `FRONTEND_PORT` | `5173` | Host port the frontend dev server binds |
| `POSTGRES_HOST_PORT` | `5433` | Host port the Docker Postgres binds |
| `OPPORTUNITY_TTL_MINUTES` | `720` | How long opportunities remain valid. Sized for manual refresh; tighten once a scheduler exists |
| `PROVIDER_CACHE_TTL_SECONDS` | `300` | How long a provider response may be reused by an *incidental* repeat fetch. `0` disables reuse. A deliberate refresh always pulls live regardless (ADR-011) |
| `QUOTE_PROVIDER` | `in_memory` | `odds_api` for live sportsbook data |
| `ODDS_API_KEY` | `""` | API key from the-odds-api.com |
| `ODDS_API_REGIONS` | `us` | Comma-separated regions. Each region multiplies the credit cost of every call |
| `ODDS_API_MARKETS` | `h2h,spreads,totals` | Comma-separated market types. Each market multiplies the credit cost of every call |

Upstream bills **credits, not requests**: `cost = [markets] x [regions]` per call. The
defaults above cost 3 credits per sport per call. Refresh is manual by design — nothing
polls — and that is the main thing keeping spend down.

## Running Tests

```bash
# Full suite (unit + integration)
uv run pytest

# Verbose output
uv run pytest -v

# Specific test file
uv run pytest backend/tests/test_engines.py

# With coverage
uv run pytest --cov=backend
```

Integration tests use SQLite for speed. Persistence behaviour is additionally proved
against migrated Postgres by tests that skip unless `STAGE2_TEST_DATABASE_URL` is set —
point it at a throwaway database, since they drop every table in it. See
`docs/testing/README.md`.

## Roadmap

| Stage | Status | Focus |
|-------|--------|-------|
| 0-6 | Done | Foundation, engines, persistence, events, ingestion, watch intents, opportunities, Odds API |
| 7 | Next | GET endpoints for browsing events/markets/quotes |
| 8 | Planned | Structured logging + audit trail |
| 9 | Planned | AI layer (advisory -- parse intent, explain, suggest) |
| 10 | Planned | Frontend (React/Next.js) |
| 11 | Planned | Deploy + CI/CD |
| 12 | Future | WebSockets, Redis, event bus, Go ingestion service |
