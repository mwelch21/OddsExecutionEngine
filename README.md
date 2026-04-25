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

## Prerequisites

- **Python 3.12+**
- **[uv](https://docs.astral.sh/uv/)** -- Python package manager
- **Docker Desktop** -- For PostgreSQL 16

Optional:
- **The Odds API key** -- For live sportsbook data ([free tier: 500 requests/month](https://the-odds-api.com))

## Getting Started

### 1. Clone and install dependencies

```bash
git clone https://github.com/mwelch21/OddsExecutionEngine.git
cd OddsExecutionEngine
uv sync --group dev
```

### 2. Configure environment

Create a `.env` file in the project root:

```env
POSTGRES_HOST=localhost
POSTGRES_DB=odds_execution
POSTGRES_USER=app
POSTGRES_PASSWORD=app
POSTGRES_PORT=5433
```

> **Port note:** Docker maps the container's internal port 5432 to host port 5433 by default. This avoids conflicts if you have a local PostgreSQL instance running on 5432. If port 5432 is free on your machine, you can change the mapping in `docker-compose.yml` and set `POSTGRES_PORT=5432` here.

To enable live odds data, add:

```env
QUOTE_PROVIDER=odds_api
ODDS_API_KEY=your_api_key_here
ODDS_API_SPORTS=icehockey_nhl,baseball_mlb
ODDS_API_REGIONS=us,us2
ODDS_API_MARKETS=h2h,spreads,totals
```

Without these, the system uses built-in fixture data (NBA Knicks vs Celtics).

### 3. Start PostgreSQL

```bash
docker compose up -d
```

### 4. Run database migrations and seed demo data

```bash
uv run odds-db-upgrade
uv run odds-db-seed-demo
```

### 5. Start the API

The API runs inside the Docker container automatically. Access it at:

```
http://localhost:8000
```

To run locally instead (e.g., for debugging):

```bash
docker compose stop api
uv run uvicorn backend.app.main:create_app --factory --host 0.0.0.0 --port 8000
```

### 6. Verify it works

```bash
# Health check
curl http://localhost:8000/health

# Open the testing dashboard (development mode only)
open http://localhost:8000/test-ui
```

The test UI provides pre-built scenarios for all endpoints -- quote refresh, recommendations, watch intents, opportunities, and live data ingestion.

## Common Commands

```bash
# Start services
docker compose up -d

# Rebuild after code changes
docker compose up -d --build

# Run database migrations
uv run odds-db-upgrade

# Seed demo data
uv run odds-db-seed-demo

# Run tests
uv run pytest

# Lint and type check
uv run ruff check backend/
uv run mypy backend/

# Inspect the database
docker compose exec postgres psql -U app -d odds_execution

# View logs
docker compose logs -f api
```

## API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/health` | Health check |
| `POST` | `/execution/recommendation` | Evaluate fillability for an order intent |
| `POST` | `/ingestion/quotes/refresh` | Refresh quotes for a single event |
| `POST` | `/ingestion/quotes/refresh-sport` | Refresh all events for a sport (live data) |
| `POST` | `/watch-intents` | Create a watch intent (monitors for target price) |
| `GET` | `/watch-intents?event_id=` | List active watch intents |
| `DELETE` | `/watch-intents/{id}` | Cancel a watch intent |
| `GET` | `/opportunities?event_id=` | List opportunities with computed validity |
| `GET` | `/test-ui` | Interactive testing dashboard (dev only) |

### Example: Get a recommendation

```bash
curl -X POST http://localhost:8000/execution/recommendation \
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
curl -X POST http://localhost:8000/ingestion/quotes/refresh-sport \
  -H 'Content-Type: application/json' \
  -d '{"sport": "icehockey_nhl"}'
```

### Example: Create a watch intent

```bash
curl -X POST http://localhost:8000/watch-intents \
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

## Database

10 tables managed via Alembic migrations:

`events`, `markets`, `market_quotes_latest`, `market_quotes_history`, `order_intents`, `execution_recommendations`, `workflow_events`, `watch_intents`, `opportunities`

### Resetting the database

```bash
docker compose down -v        # removes the volume (all data lost)
docker compose up -d
uv run odds-db-upgrade
uv run odds-db-seed-demo
```

## Configuration Reference

| Variable | Default | Description |
|----------|---------|-------------|
| `APP_ENV` | `development` | `production` enforces security constraints |
| `POSTGRES_DB` | `odds_execution` | Database name |
| `POSTGRES_USER` | `app` | Database user |
| `POSTGRES_PASSWORD` | `app` | Database password (must change in production) |
| `POSTGRES_HOST` | `postgres` | `localhost` when running outside Docker |
| `POSTGRES_PORT` | `5432` | Host port is 5433 by default in docker-compose |
| `OPPORTUNITY_TTL_MINUTES` | `5` | How long opportunities remain valid |
| `QUOTE_PROVIDER` | `in_memory` | `odds_api` for live sportsbook data |
| `ODDS_API_KEY` | `""` | API key from the-odds-api.com |
| `ODDS_API_SPORTS` | `icehockey_nhl,baseball_mlb` | Comma-separated sport keys |
| `ODDS_API_REGIONS` | `us,us2` | Comma-separated regions |
| `ODDS_API_MARKETS` | `h2h,spreads,totals` | Comma-separated market types |

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

Integration tests use SQLite for speed. The Docker PostgreSQL instance is used for the running application and manual testing.

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
