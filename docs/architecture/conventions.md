# Architecture Conventions

## Persistence

- Migrations live in `backend/db/migrations`.
- Schema changes must ship with a migration file.
- App startup must not call schema creation APIs such as `create_all()`.
- SQLAlchemy schema definitions in application code are the canonical app-side schema reference, but migrations are the operational source of schema changes.
- Demo or fixture data must be loaded explicitly, never as an implicit side effect of normal app boot.

## Layering

- Dependency direction stays `api -> application -> domain`.
- Infrastructure stays behind ports or application-facing abstractions.
- Deterministic engines hold pricing, matching, ranking, nearest-miss, and watch logic.
- Routes stay thin and must not own business logic.

## Persistence structure

- Persistence adapters, schema metadata, migration helpers, and seed helpers live under `backend/app/infrastructure/persistence`.
- Repositories and unit-of-work implementations should use constructor injection.
- Market identity logic that affects persistence keys should live in a shared helper, not duplicate ad hoc formatting.

## Testing

- DB-backed flows must have integration coverage against migrated Postgres.
- Postgres is the required truth path for persistence correctness.
- SQLite may be used only for lightweight local smoke or convenience coverage.
- SQLite passing is never sufficient proof that Postgres persistence behavior is correct.
- Tests must prepare schema through migrations, not through runtime bootstrapping.
- Stage 3 event-layer work must start from migrated schema and explicit seed tooling, not transitional bootstrap helpers.
- Full testing strategy, layer definitions, and maintenance instructions live in `docs/testing/README.md`.

## Observability

- Service workflows should emit structured logs at start, success, and failure boundaries.
- Request correlation should flow through application logs with a request id header/context.
- Logging should stay in infrastructure and application orchestration layers, not deterministic domain models.

## Stage 3 landing zones

- Domain event types should live in `backend/app/domain/events.py` or an adjacent `domain/events/` package.
- Publisher ports should live in `backend/app/application/ports.py` or an adjacent application ports module.
- Publisher adapters should live under `backend/app/infrastructure/publishers`.
- `workflow_events` schema ownership belongs to stage 3 migrations under `backend/db/migrations`.
- Workflow events must be staged inside the unit of work, persisted in the same transaction, and published only after commit succeeds.

## Stage 4 landing zones

- Quote ingestion orchestration should live in an application service, not in routers or seed helpers.
- Provider abstractions should be application-facing ports with mock implementations under `backend/app/infrastructure`.
- Quote normalization should stay deterministic and map into canonical `Quote` values before persistence.
- Quote ingestion persistence should upsert `market_quotes_latest`, append `market_quotes_history`, and emit workflow events through the same post-commit publisher path.

## Decisions log policy

- Add a decision entry when changing migration strategy, schema ownership, persistence layout, layer boundaries, event model boundaries, or other major architectural rules.
- Add to conventions when the rule is general and expected to remain true across features.
- Update both docs when a large change introduces both a one-time decision and a standing rule.

## Watch intent TTL

- `watch_intents.expires_at` is nullable; `NULL` means the watch has no TTL and never expires by time.
- Expiry is a domain rule, not a query: `WatchIntent.is_expired_at` is the single definition, used by both evaluation and reads so the two cannot disagree.
- Watches past their TTL are retired to `expired` and emit `WatchIntentExpired` **before** evaluation runs. A watch with a reachable target must never produce an opportunity after its TTL has passed.
- Expiry is applied when an event is next evaluated, so a watch whose TTL passed while nothing refreshed is still stored as `active`. Reads project the correct status via `effective_status`; they never write. `?status=expired` therefore also scans stored-active rows, otherwise such a watch would be missing from both the active and expired listings.
- Creating a watch whose TTL has already passed stores it, but skips the immediate evaluation: it can never fill.
