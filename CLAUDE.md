# CLAUDE.md — OddsExecutionEngine

## Project Overview

Sports market execution platform. Takes an order intent (bet request with target odds), finds matching quotes from sportsbooks, and recommends whether the order is fillable at the desired price.

**Stack:** Python 3.12 · FastAPI · PostgreSQL 16 · SQLAlchemy Core · psycopg3 · Alembic · Docker
**Status:** Stages 0–5 complete. Stage 6 (AI Layer) is next.

## Architecture

Strict layered architecture. Dependency arrows go one direction only:

```
api/ → application/ → domain/ (pure, zero imports)
                    → engines/ (pure functions, zero I/O)
                    → infrastructure/ (DB, providers, publishers)
```

**Invariant:** `domain/` has zero external imports. `engines/` has no DB/HTTP imports.

### Key Patterns

- **Deterministic engines:** NormalizationEngine, QuoteMatchingEngine, PriceComparisonService, RecommendationEngine, WatchEvaluationEngine, OpportunityValidityEngine — all pure functions. Same input = same output. No I/O ever.
- **Unit of Work + staged events:** Events staged during UoW lifecycle, persisted in same transaction as data, published only after successful commit. Rollback discards all events.
- **Domain models:** Frozen Pydantic (`extra="forbid"`) — immutable value objects.
- **Ports & adapters:** Application layer depends on Protocol interfaces (`ports.py`). Infrastructure implements them.
- **Market identity:** Unique constraint `(event_id, market_type, selection, line_key)` via `build_line_key()` helper (solves NULL uniqueness in SQL).
- **Latest vs history:** `market_quotes_latest` (upsert via DELETE+INSERT) vs `market_quotes_history` (append-only).

## Package Structure

```
backend/
├── app/
│   ├── main.py                     # App factory, middleware, DI wiring
│   ├── config.py                   # pydantic-settings, DB URL, security validation
│   ├── api/                        # Routers + request/response schemas
│   ├── domain/
│   │   ├── models.py               # Value objects: Quote, OrderIntent, ExecutionRecommendation…
│   │   └── events.py               # WorkflowEvent + 8 event types
│   ├── application/
│   │   ├── ports.py                # Protocol interfaces (UoW, Publisher, Provider)
│   │   ├── recommendation_service.py
│   │   ├── quote_ingestion_service.py
│   │   └── watch_intent_service.py
│   ├── engines/                    # Pure deterministic logic (NO I/O)
│   │   ├── normalization_engine.py
│   │   ├── quote_matching_engine.py
│   │   ├── price_comparison_engine.py
│   │   ├── recommendation_engine.py
│   │   ├── watch_evaluation_engine.py
│   │   └── opportunity_validity_engine.py
│   └── infrastructure/
│       ├── quote_provider.py       # InMemoryQuoteProvider (fixture data)
│       ├── publishers/             # LoggingPublisher, InMemoryPublisher
│       ├── observability/          # Structured logging, request context
│       └── persistence/            # DB session, schema, UoWs, migrations, seed
└── tests/                          # conftest.py, test_*.py
```

## Common Commands

```bash
# Start services
docker compose up -d

# Run database migrations
uv run odds-db-upgrade

# Seed demo data
uv run odds-db-seed-demo

# Run tests
uv run pytest

# Lint
uv run ruff check backend/
uv run mypy backend/

# API (when running)
curl http://localhost:8000/health
curl -X POST http://localhost:8000/ingestion/quotes/refresh -H 'Content-Type: application/json' -d '{"event_id":"evt-1"}'
curl -X POST http://localhost:8000/execution/recommendation -H 'Content-Type: application/json' -d '{"event_id":"evt-1","market_type":"moneyline","selection":"Team A","target_price":-110}'
```

## API Endpoints

| Method | Path | Status |
|--------|------|--------|
| GET | `/health` | ✅ |
| POST | `/execution/recommendation` | ✅ |
| POST | `/ingestion/quotes/refresh` | ✅ |
| POST | `/watch-intents` | ✅ |
| GET | `/watch-intents?event_id=` | ✅ |
| DELETE | `/watch-intents/{id}` | ✅ |
| GET | `/opportunities?event_id=` | ✅ |
| GET | `/test-ui` | ✅ (dev only) |

### Request Validation

- `MONEYLINE` → `line` must be absent/null
- `SPREAD` / `TOTAL` → `line` required
- `TOTAL` → `selection` must be `"over"` or `"under"`

## Database (10 tables)

`events`, `markets`, `market_quotes_latest`, `market_quotes_history`, `order_intents`, `execution_recommendations`, `workflow_events`, `watch_intents`, `opportunities`

Migrations in `backend/db/migrations/versions/`.

## Domain Events

8 event types: `OrderIntentSubmitted`, `ExecutionRecommendationGenerated`, `QuotesRefreshed`, `QuoteUpdated`, `MarketSnapshotCreated`, `WatchIntentCreated`, `WatchIntentCancelled`, `OpportunityIdentified`

All follow the staged-commit-then-publish pattern via UoW.

## Development Rules

1. **Never add I/O to engines.** They are pure functions. If you need data, pass it in as arguments.
2. **Never reverse dependency arrows.** domain/ imports nothing. engines/ imports only domain/. infrastructure/ imports domain/ but never application/ or api/.
3. **AI endpoints (Stage 6) are advisory only.** They never affect fillability, ranking, or matching logic.
4. **All domain models are frozen.** Use `DomainModel` base class (Pydantic, `frozen=True`, `extra="forbid"`).
5. **Events go through UoW.** Call `stage_event()` during the workflow. Events persist in the same transaction as business data. Publisher runs post-commit only.
6. **Tests live in `backend/tests/`.** Run with `uv run pytest`. Integration tests need a running Postgres (use Docker).
7. **Config:** pydantic-settings loads from env vars / `.env`. Production rejects default passwords.
8. **Linting:** ruff (E, F, I, B rules) + mypy (strict). Line length 100.

## Configuration

Environment variables (or `.env` file):

| Variable | Default | Notes |
|----------|---------|-------|
| `APP_ENV` | `development` | `production` enforces security constraints |
| `POSTGRES_DB` | `odds_execution` | |
| `POSTGRES_USER` | `app` | |
| `POSTGRES_PASSWORD` | `app` | Must change in production |
| `POSTGRES_HOST` | `localhost` | `postgres` inside Docker |
| `POSTGRES_PORT` | `5432` | |
| `OPPORTUNITY_TTL_MINUTES` | `5` | How long opportunities remain valid |

## Knowledge Base (claude-memory-compiler)

This project includes an auto-compiling knowledge base in `claude-memory-compiler/`. Claude Code hooks automatically:
- **SessionStart:** Injects knowledge base index into context
- **PreCompact:** Captures context before auto-compaction
- **SessionEnd:** Extracts conversation → daily log, spawns background flush

### Manual knowledge base commands

```bash
cd claude-memory-compiler
uv run python scripts/compile.py                          # compile new daily logs
uv run python scripts/query.py "question"                  # query knowledge base
uv run python scripts/query.py "question" --file-back      # query + save answer
uv run python scripts/lint.py                              # health checks
uv run python scripts/lint.py --structural-only            # free structural checks
```

### Knowledge base structure

```
claude-memory-compiler/
├── daily/              # Conversation logs (append-only, never edit)
├── knowledge/
│   ├── index.md        # Master catalog (read FIRST for any query)
│   ├── log.md          # Build log
│   ├── concepts/       # Atomic knowledge articles
│   ├── connections/    # Cross-cutting insights
│   └── qa/             # Filed query answers
├── hooks/              # Claude Code hooks (session-start, session-end, pre-compact)
└── scripts/            # compile.py, query.py, lint.py, flush.py
```

### Knowledge base conventions

- Articles use Obsidian-style `[[wikilinks]]` with paths relative to `knowledge/`
- Every article has YAML frontmatter (title, sources, created, updated)
- Encyclopedia style — factual, concise, self-contained
- File naming: lowercase, hyphens for spaces
- Prefer updating existing articles over creating near-duplicates
- See `claude-memory-compiler/AGENTS.md` for full schema reference

## Roadmap

| Stage | Status | Focus |
|-------|--------|-------|
| 0–5 | ✅ | Foundation, engines, persistence, events, ingestion, watch intents, opportunities |
| 6 | 🔜 | AI Layer (advisory only — parse intent, explain, suggest) |
| 7 | 🔜 | GET endpoints for browsing events/markets/quotes |
| 8 | 🔜 | Full structured logging + audit trail |
| 9 | ❌ | WebSockets, Redis, event bus, Go ingestion service |
