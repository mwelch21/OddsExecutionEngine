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

## Branching and Pull Requests

`development` is the default branch and the integration target. `main` is the promotion target.

```
feature branch  ->  development  ->  main
```

- Cut feature branches from `development`, and open pull requests **against `development`**.
- Promote with a `development` -> `main` pull request when a batch of work is ready.
- Never push directly to `development` or `main`. Both are protected; a direct push is rejected with `protected branch hook declined`.

### Closing issues from a pull request

GitHub only honours `Closes #N` when the pull request merges into the **default** branch, which is `development`.

A pull request targeting `main` will merge fine and silently leave its issue open. That is not a formatting problem and re-wording the trailer will not fix it — the base branch is wrong. Retarget to `development`, or close the issue by hand and say why.

This has already bitten this repo: #16 and #18 both targeted `main`, so #11, #12, and #13 had to be closed manually after the work shipped.

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
- `recommendation_engine`, `watch_evaluation_engine`, `opportunity_validity_engine`

### Event Model

Define and emit explicit events. Names below reflect the `Literal` event types actually
defined in `backend/app/domain/events.py` on `main` — verify with:
`grep -rhoE 'Literal\["[A-Za-z]+"\]' backend/app/domain/events.py`.

Implemented:

- `QuotesRefreshed`, `QuoteUpdated`, `MarketSnapshotCreated`
- `OrderIntentSubmitted`, `ExecutionRecommendationGenerated`
- `WatchIntentCreated`, `WatchIntentCancelled`, `WatchIntentExpired`, `WatchIntentTriggered`
- `OpportunityIdentified`

Planned, not yet implemented (do not assume these exist in code):

- `TargetPriceStillUnfilled`, `MarketMovedAwayFromTarget` (nearest-miss / drift signals)
- `AIExplanationGenerated` (depends on the AI layer, which has not been built)

Events are staged inside the unit of work, persisted in the same transaction as domain writes, and published only after commit succeeds. Domain event types live in `backend/app/domain/events.py`. Publisher adapters live under `backend/app/infrastructure/publishers/`.

## Storage

Postgres. Separate latest-state and history.

Tables: `events`, `event_participants`, `markets`, `market_quotes_latest`, `market_quotes_history`, `order_intents`, `watch_intents`, `execution_recommendations`, `opportunities`, `workflow_events`.

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

Verified against `backend/app/main.py` route registration on `main`.

Core:

- `POST /execution/recommendation`

Ingestion:

- `POST /ingestion/quotes/refresh`
- `POST /ingestion/quotes/refresh-sport`

Monitoring:

- `POST /watch-intents` (evaluates immediately; may return `triggered` with the opportunity nested)
- `GET /watch-intents` (optional `event_id` and `status` filters)
- `GET /watch-intents/{id}`
- `DELETE /watch-intents/{id}` (409 if the watch already `triggered`)
- `GET /opportunities` (optional `event_id` filter)
- `GET /opportunities/{id}`

Dev only:

- `GET /test-ui`

Planned, not yet implemented:

- `GET /events`, `GET /events/{event_id}/markets`, `GET /events/{event_id}/quotes`
- `POST /ai/parse-intent`, `POST /ai/explain`, `POST /ai/suggest-actions` (AI layer)

## Service Catalog

See `docs/flows/_index.md` for full flow documentation.

| Service | Location | Responsibility |
|---|---|---|
| QuoteIngestionService | `application/quote_ingestion_service.py` | Provider fetch -> normalization -> persistence -> event publish |
| RecommendationService | `application/recommendation_service.py` | Intent persistence -> quote matching -> recommendation -> event publish |
| WatchIntentService | `application/watch_intent_service.py` | Watch intent persistence -> opportunity evaluation -> validity check -> event publish |
| NormalizationEngine | `engines/normalization_engine.py` | Filters raw provider quotes into canonical form |
| QuoteMatchingEngine | `engines/quote_matching_engine.py` | Matches quotes against order intent criteria |
| RecommendationEngine | `engines/recommendation_engine.py` | Ranks matched quotes, determines fillability |
| WatchEvaluationEngine | `engines/watch_evaluation_engine.py` | Evaluates watch intents against quotes, produces opportunities |
| OpportunityValidityEngine | `engines/opportunity_validity_engine.py` | Determines whether an opportunity is still valid given a TTL |
| TheOddsApiProvider | `infrastructure/odds_api_provider.py` | Live sportsbook quote provider (The Odds API) |

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

### Stage 6: Live Odds Integration (implemented)
Real odds API provider (The Odds API) for live sportsbook data, opportunity identity/idempotency
constraints, flexible event-participant schema. See `docs/architecture/stages-5-6-data-flows.md`.
This stage superseded the "AI Layer" originally planned for Stage 6 below — that work has not
started yet and now falls under Stage 7+.

### Stage 7+ (planned): AI Layer, API Expansion, Observability, WebSockets, Redis, event bus, Go ingestion service, backtesting.
AI layer (parse intent, generate explanation, suggest actions; AI support without deterministic
leakage) has not been built yet — no `/ai/*` routes or AI adapters exist on `main`.

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
