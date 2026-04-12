# Architecture Decisions

## ADR-001: Keep migrations in the backend repo

- Status: accepted
- Date: 2026-04-11

### Context

Stage 2 introduced persistent storage and schema ownership. The backend is still the only service that owns this schema.

### Decision

Keep migration files in this repository under `backend/db/migrations` instead of creating a separate database project.

### Why

- app code, repositories, tests, and schema changes evolve together
- one PR can change behavior and schema consistently
- agentic implementation and review stay schema-aware without cross-repo coordination

### Rejected alternatives

- separate DB repo now: adds overhead before multiple services own the schema

### Consequences

- schema changes must land with migration files in this repo
- future split is allowed if schema ownership broadens

## ADR-002: No runtime schema creation in app startup

- Status: accepted
- Date: 2026-04-11

### Context

`metadata.create_all()` in app startup creates hidden schema mutation and makes production state depend on boot order.

### Decision

All schema creation and evolution must happen through explicit migrations. App startup must not mutate schema.

### Why

- predictable deploys
- visible schema history
- safer production operations
- tests can prove the migration path directly

### Rejected alternatives

- keep `create_all()` for convenience: too implicit and unsafe for long-term use

### Consequences

- local/dev setup requires a migration step
- deploy workflows must run migrations before app traffic

## ADR-003: Persist latest and history separately

- Status: accepted
- Date: 2026-04-11

### Context

Recommendation paths want fast latest-state reads, while audit and future analytics want quote history.

### Decision

Use `market_quotes_latest` for current execution reads and `market_quotes_history` for append-style historical storage.

### Why

- simple query path for recommendation
- preserves audit trail
- matches product requirement for latest vs history split

### Rejected alternatives

- history-only queries for everything: slower and noisier read path
- latest-only storage: loses auditability

### Consequences

- quote ingestion must maintain both tables consistently

## ADR-004: Record reusable engineering rules in conventions

- Status: accepted
- Date: 2026-04-11

### Context

Architecture and workflow expectations were scattered across code, tests, and chat history.

### Decision

Store major one-time choices in `docs/architecture/decisions.md` and general standing rules in `docs/architecture/conventions.md`.

### Why

- gives agents and humans one place to check
- reduces repeated drift in architecture choices
- makes rationale visible instead of implicit

### Rejected alternatives

- keep all rules only in `agents.md`: too mixed between process and architecture

### Consequences

- agents must read and update these docs when making material architecture changes

## ADR-005: Stage 2 enhanced is the operational baseline before event work

- Status: accepted
- Date: 2026-04-11

### Context

Stage 2 introduced explicit migrations, persistence adapters, and seed tooling. Stage 3 should not mix event-layer design with unfinished persistence workflow cleanup.

### Decision

Treat stage 2 enhanced as the required operational baseline. Before event-layer work, the repo must have explicit migration commands, explicit demo seed commands, and clear Postgres-first persistence test policy.

### Why

- keeps event work focused on event boundaries instead of DB workflow cleanup
- makes local and CI setup repeatable
- prevents SQLite convenience coverage from being mistaken for persistence truth

### Rejected alternatives

- start stage 3 while persistence ergonomics are still transitional

### Consequences

- Postgres remains the required integration truth path
- SQLite is limited to smoke or convenience coverage
- stage 3 begins only after migration and seed workflows are explicit

## ADR-006: Persist workflow events and publish only after commit

- Status: accepted
- Date: 2026-04-12

### Context

Stage 3 introduces the first explicit event boundary around recommendation generation. The system needs an audit trail of emitted workflow events and must avoid publishing events for transactions that later roll back.

### Decision

Persist workflow events in the `workflow_events` table within the same transaction as recommendation writes, and publish them only after a successful commit.

### Why

- preserves an append-only workflow audit trail
- keeps event visibility aligned with committed database state
- creates a simple outbox-style boundary without introducing a full event bus yet

### Rejected alternatives

- publish before commit: risks leaking rolled-back events
- publish without persistence: loses durable workflow history
- persist without publishing: delays stage 3 integration boundary value

### Consequences

- recommendation workflows must stage events during the unit of work
- rollback paths must clear staged events and publish nothing
- initial publishers remain synchronous and process-local
