# OddsExecutionEngine

Backend system for evaluating fillability and executing best available odds across fragmented sportsbook markets.

## Default Mode

- Use caveman `full` by default.
- Stay in caveman until user says `stop caveman` or `normal mode`.
- Keep answers short, direct, technical.

## Mission

Build backend-first sports market execution platform. System answers:

- Is target price fillable now?
- What sportsbook gives best execution?
- If not fillable, what is nearest miss?
- What watch or opportunity signals should fire?
- Optional: AI parse/explain/suggest, never AI decide pricing logic.

Optimize for backend/system design signal, not frontend polish.

## Product Scope

User intent examples:

- `Knicks moneyline +120 or better`
- `Over 221.5 at -110 or better`
- `Alert me when Celtics spread becomes -105 or better`

Core flow:

1. Parse or accept structured intent.
2. Read latest quotes across books.
3. Match correct market.
4. Determine fillability.
5. Rank best execution.
6. Return nearest miss if needed.
7. Persist latest and history.
8. Emit workflow/domain events.
9. Support watch intents.
10. Add AI only as support layer.

## Tech Stack

Python 3.12, FastAPI, PostgreSQL, Docker Compose, uv, Alembic, Ruff, mypy, pytest.

## Quick Reference

```bash
# Install deps
uv sync --group dev

# Tests / lint / typecheck
uv run pytest
uv run ruff check .
uv run mypy backend

# Full local stack
docker compose up --build -d
docker compose exec -T api uv run alembic -c backend/db/alembic.ini upgrade head
docker compose exec -T api uv run odds-db-seed-demo
docker compose exec -T api uv run pytest

# End-to-end verification
./scripts/verify_stage2_5.sh
```

## Project Layout

```
backend/
  app/
    main.py, config.py
    api/          # thin routes, no business logic
    domain/       # entities, value objects, policies, events
    application/  # workflows, services, ports, orchestration
    engines/      # deterministic decision engines
    infrastructure/  # db, repositories, providers, publishers, AI adapters
  db/
    migrations/   # Alembic migrations (schema source of truth)
  tests/
```

## Architecture

### Non-Negotiables

- Deterministic core. Matching, comparison, ranking, nearest miss, watch logic must be pure/testable.
- Event-driven design. Sync implementation OK first; event boundaries still explicit.
- Clean architecture. Dependency direction: `api -> application -> domain`, infra behind ports.
- Thin API. Business logic stays out of routes.
- Postgres for persistence.
- Constructor injection only. No heavy DI framework.

### Layering

- Dependency direction: `api -> application -> domain`.
- Infrastructure stays behind ports or application-facing abstractions.
- Routes stay thin and must not own business logic.
- Deterministic engines hold pricing, matching, ranking, and watch logic.

Full details in `docs/architecture/conventions.md` and `docs/architecture/decisions.md`.

### Core Domain Objects

- `Event`, `Market`, `Quote`, `OrderIntent`, `WatchIntent`
- `ExecutionRecommendation`, `OpportunitySignal`, `MarketSnapshot`

### Deterministic Engines

- `normalization_engine`, `quote_matching_engine`, `price_comparison_engine`
- `recommendation_engine`, `watch_evaluation_engine`, `opportunity_engine`

### Event Model

Define and emit explicit events. Baseline set:

- `QuotesRefreshed`, `QuoteUpdated`, `MarketSnapshotCreated`
- `OrderIntentSubmitted`, `ExecutionRecommendationGenerated`
- `WatchIntentSubmitted`, `TargetPriceBecameFillable`, `TargetPriceStillUnfilled`, `MarketMovedAwayFromTarget`
- `OpportunityDetected`, `AIExplanationGenerated`

Events are staged inside the unit of work, persisted in the same transaction as domain writes, and published only after commit succeeds. Domain event types live in `backend/app/domain/events.py`. Publisher adapters live under `backend/app/infrastructure/publishers/`.

## Storage

Postgres. Separate latest-state and history.

Tables: `events`, `markets`, `market_quotes_latest`, `market_quotes_history`, `order_intents`, `watch_intents`, `execution_recommendations`, `workflow_events`, `opportunity_signals`.

- latest drives recommendation/read paths
- history drives audit/future analytics

### Persistence Rules

- Migrations in `backend/db/migrations/`. Schema changes must ship with a migration file.
- App startup must not call `create_all()` or any schema creation API.
- Postgres is the required persistence truth path.
- SQLite may be used only for lightweight local smoke or convenience coverage.

### Database Commands

```bash
docker compose exec -T api uv run alembic -c backend/db/alembic.ini upgrade head
docker compose exec -T api uv run odds-db-seed-demo
docker compose exec postgres psql -U app -d odds_execution
```

## API Surface

Core:

- `POST /execution/recommendation`
- `GET /events`
- `GET /events/{event_id}/markets`
- `GET /events/{event_id}/quotes`

Monitoring:

- `POST /watch-intents`
- `GET /watch-intents`
- `GET /opportunities`

AI later:

- `POST /ai/parse-intent`
- `POST /ai/explain`
- `POST /ai/suggest-actions`

## Service Catalog

See `docs/flows/_index.md` for full flow documentation.

| Service | Location | Responsibility |
|---|---|---|
| QuoteIngestionService | `application/quote_ingestion_service.py` | Provider fetch -> normalization -> persistence -> event publish |
| RecommendationService | `application/recommendation_service.py` | Intent persistence -> quote matching -> recommendation -> event publish |
| NormalizationEngine | `engines/normalization_engine.py` | Filters raw provider quotes into canonical form |
| QuoteMatchingEngine | `engines/quote_matching_engine.py` | Matches quotes against order intent criteria |
| RecommendationEngine | `engines/recommendation_engine.py` | Ranks matched quotes, determines fillability |
| WatchIntentService | `application/watch_intent_service.py` | Watch intent CRUD -> persistence -> event publish |
| WatchEvaluationService | `application/watch_evaluation_service.py` | Watch evaluation -> opportunity signals -> status updates -> event publish |
| WatchEvaluationEngine | `engines/watch_evaluation_engine.py` | Separates expired watches, matches quotes, determines triggers |

## Build Order

### Stage 0: Foundation
FastAPI + uv + Docker + Postgres, lint + typing + pytest, base structure.

### Stage 1: Deterministic Core
Domain models, matching/comparison/recommendation engines, recommendation service + endpoint, unit tests.

### Stage 2 Enhanced: Persistence Discipline
Schema, versioned migrations, repositories/UoW/persistence adapters, DB-backed recommendation flow, integration tests against migrated Postgres, explicit seed flow, no runtime schema creation.

### Stage 3: Event Layer
Event classes, publisher port, in-memory/log publisher, workflow emission.

### Stage 4: Quote Ingestion
Provider port, mock provider, normalization, latest/history update flow.

### Stage 5: Monitoring + Opportunities
Watch intent model, watch evaluation engine, opportunity engine, monitoring endpoints.

### Stage 6: AI Layer
Parse intent, generate explanation, suggest actions. AI support without deterministic leakage.

### Stage 7+: API Expansion, Observability, WebSockets, Redis, event bus, Go ingestion service, backtesting.

## Testing

- DB-backed flows must have integration coverage against migrated Postgres.
- Tests must prepare schema through migrations, not runtime bootstrapping.
- SQLite passing is never sufficient proof that Postgres persistence behavior is correct.
- Write tests for behavior, not internals.
- Full testing strategy: `docs/testing/README.md`.

Required coverage: quote matching, odds comparison, ranking, nearest miss, monitoring logic (unit); recommendation endpoint, DB-backed flows (integration); quote update -> opportunity, watch intent -> fillability event (workflow).

## Coding Rules

- Use shared Pydantic base model for domain entities and value objects. No dataclasses for domain model types.
- Separate API transport schemas from router modules. No request/response models in route handler files.
- Implement deterministic engines as class-based services with injected dependencies when needed.
- Keep persistence code under `backend/app/infrastructure/persistence`.
- Put migration files under `backend/db/migrations`.
- Never rely on runtime `create_all()` or equivalent boot-time schema mutation.
- Schema changes require a tracked migration file plus corresponding tests.
- Keep application services orchestrating injected collaborators, not imported free-function pipelines.
- Use type hints. Keep functions small. Keep domain pure. Keep logic deterministic. Keep API thin.
- Do not ignore Ruff import sorting errors.
- Before completing implementation work, run: `pytest`, `ruff check .`, `mypy backend`.
- Preserve user changes. Never revert unrelated work.

## Context Management Rules

- Read only files needed for current task.
- Prefer targeted searches. Avoid loading whole repo.
- After reading large file, summarize in working memory; do not reread unless changed.
- Do not restate product vision unless task depends on it.
- When editing, keep scope tight. Touch smallest valid set of files.
- Prefer existing patterns over exploratory rewrites.
- When blocked by ambiguity, inspect codebase first, ask user last.
- Before changing architecture/migrations/persistence/repo-wide rules, read `docs/architecture/decisions.md` and `docs/architecture/conventions.md`.
- If task changes major architectural choice, update `docs/architecture/decisions.md`.
- If task introduces/changes standing rule, update `docs/architecture/conventions.md`.

## Anti-Goals

- No UI-heavy betting app
- No premature microservices/infrastructure
- No replacing deterministic logic with AI
- No social/community features
- No optimizing for novelty over system behavior

## Done Standard

Repo should show: clean architecture, working backend, passing tests, docs, clear system explanation. Optimize for signal, not perfection.

## Agent Skills

### Issue tracker

Issues are tracked in GitHub Issues on `mwelch21/OddsExecutionEngine`. See `docs/agents/issue-tracker.md`.

### Triage labels

Default label vocabulary (labels match canonical role names). See `docs/agents/triage-labels.md`.

### Domain docs

Single-context layout: one `CONTEXT.md` + `docs/adr/` at the repo root. See `docs/agents/domain.md`.
