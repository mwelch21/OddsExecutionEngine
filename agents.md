# Agent Guide: Odds Execution Engine

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

## Non-Negotiables

- Deterministic core. Matching, comparison, ranking, nearest miss, watch logic must be pure/testable.
- Event-driven design. Sync implementation OK first; event boundaries still explicit.
- Clean architecture. Dependency direction: `api -> application -> domain`, infra behind ports.
- Thin API. Business logic stays out of routes.
- Postgres for persistence.
- Constructor injection only. No heavy DI framework.

## Architecture

Layers:

- `domain`: entities, value objects, policies, events
- `application`: workflows, services, ports, orchestration
- `engines`: deterministic decision engines
- `infrastructure`: db, repositories, providers, publishers, AI adapters
- `api`: transport, validation, response mapping

Core domain objects:

- `Event`
- `Market`
- `Quote`
- `OrderIntent`
- `WatchIntent`
- `ExecutionRecommendation`
- `OpportunitySignal`
- `MarketSnapshot`

Deterministic engines:

- `normalization_engine`
- `quote_matching_engine`
- `price_comparison_engine`
- `recommendation_engine`
- `watch_evaluation_engine`
- `opportunity_engine`

## Event Model

Define and emit explicit events. Baseline set:

- `QuotesRefreshed`
- `QuoteUpdated`
- `MarketSnapshotCreated`
- `OrderIntentSubmitted`
- `ExecutionRecommendationGenerated`
- `WatchIntentSubmitted`
- `TargetPriceBecameFillable`
- `TargetPriceStillUnfilled`
- `MarketMovedAwayFromTarget`
- `OpportunityDetected`
- `AIExplanationGenerated`

## Storage

Use Postgres. Keep separate latest-state and history.

Tables:

- `events`
- `markets`
- `market_quotes_latest`
- `market_quotes_history`
- `order_intents`
- `watch_intents`
- `execution_recommendations`
- `workflow_events`
- `opportunity_signals`

Rule:

- latest drives recommendation/read paths
- history drives audit/future analytics

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

## Build Order

### Stage 0: Foundation

- FastAPI + `uv` + Docker + Postgres
- lint + typing + pytest
- base structure + README

Deliverable: runnable backend with DB and tests.

### Stage 1: Deterministic Core

- define domain models
- build matching/comparison/recommendation engines
- add recommendation service
- add endpoint
- add unit tests

Deliverable: mock-data recommendation flow.

### Stage 2: Persistence

- schema
- repositories
- DB-backed recommendation flow
- integration tests

Deliverable: latest/history persistence working.

### Stage 3: Event Layer

- event classes
- publisher port
- in-memory/log publisher
- workflow emission

Deliverable: event boundary established.

### Stage 4: Quote Ingestion

- provider port
- mock provider
- normalization
- latest/history update flow

Deliverable: ingestion pipeline working.

### Stage 5: Monitoring + Opportunities

- watch intent model
- watch evaluation engine
- opportunity engine
- monitoring endpoints

Deliverable: alerts and signals working.

### Stage 6: AI Layer

- parse intent
- generate explanation
- suggest actions

Deliverable: AI support without deterministic leakage.

### Stage 7: API Expansion

- read endpoints
- stronger response models

### Stage 8: Observability

- structured logging
- audit trail

### Stage 9: Later

- WebSockets
- Redis cache
- event bus
- Go ingestion service
- backtesting engine

## Tests Required

Unit:

- quote matching
- odds comparison
- ranking
- nearest miss
- monitoring logic

Integration:

- recommendation endpoint
- DB-backed flows

Workflow:

- quote update -> opportunity
- watch intent -> fillability event

## Context Management Rules

Goal: minimize token burn and duplicate reading.

- Read only files needed for current task.
- Prefer targeted `rg`, `sed`, file slices. Avoid loading whole repo.
- After reading large file, summarize it in working memory; do not reread unless file changed or summary insufficient.
- Do not restate product vision unless task depends on it.
- When editing, keep scope tight. Touch smallest valid set of files.
- Prefer existing patterns over exploratory rewrites.
- For follow-up turns, assume prior local findings still valid unless user or git state changed.
- If task is narrow, do not inspect unrelated stages/roadmap sections.
- If user asks implementation, execute after enough context; do not spend turns on broad planning unless blocked.
- When blocked by ambiguity, inspect codebase first, ask user last.

## Coding Rules

- Use type hints.
- Keep functions small.
- Keep domain pure.
- Keep logic deterministic.
- Keep API thin.
- Write tests for behavior, not internals.
- Preserve user changes. Never revert unrelated work.

## Anti-Goals

Do not:

- build UI-heavy betting app
- overbuild microservices/infrastructure early
- replace deterministic logic with AI
- add social/community features
- optimize for novelty over system behavior

## Done Standard

Repo should show:

- clean architecture
- working backend
- passing tests
- docs
- clear system explanation

Optimize for signal, not perfection.
