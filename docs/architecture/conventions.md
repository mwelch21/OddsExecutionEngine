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

## Stage 5 landing zones

- Watch lifecycle state lives in `watch_intents`; opportunity signals are denormalized into `opportunity_signals` and must stay readable without joins.
- Watch evaluation logic stays in `backend/app/engines/watch_evaluation_engine.py` and must remain pure: evaluation time is injected, never read from the clock inside the engine.
- Watch evaluation reuses `PriceComparisonService` so watch fillability and recommendation fillability cannot diverge.
- Watch reads, opportunity creation, watch status updates, and staged events for one evaluation pass belong to a single `WatchEvaluationUnitOfWork` transaction.
- Cancellation is a soft status change, never a row delete: terminal watch states must stay auditable.
- Cross-service orchestration between quote ingestion and watch evaluation stays in the router until pub/sub exists (see ADR-008). Measured cost of inline evaluation: flat below ~2k active watches on one event, then linear at roughly 9µs per watch (10 quotes per refresh). Refresh doubles at ~10k watches on a single event. Cost is O(watches × quotes), so more books and markets move that threshold down proportionally.
- `opportunity_signals` carries `line` even though issue #11's column list omits it: market identity in this repo is `(event, market_type, selection, line_key)` per `uq_markets_identity`, so a signal without `line` cannot identify its own market for spread and total watches.

## Stage 5 known limitations

- Watch triggering is one-shot: a watch reaches `triggered` and is never evaluated again. Re-armable watches cannot simply reset the status to `active` — fillability is a bare `price >= target` comparison with no memory, so a price resting at or oscillating around the target would emit a signal on every quote refresh. Re-arm requires hysteresis, a cooldown, or a max-fire cap, and is a design decision rather than a status change.
- Creating a watch does not evaluate it. A watch whose target is already met stays `active` until the next quote refresh for its event. This is intended: the watch is picked up by the first sweep, and evaluating at creation would couple the create path to the evaluation service for no correctness gain.
- Expiry stays lazy in storage, but reads project it. `WatchIntent.effective_status` reports a stored-`active` watch as `expired` once `expires_at` has passed, so `?status=active` never returns a watch that can no longer trigger. The stored row is still corrected by the next evaluation; reads never write.
- There is no user or ownership concept yet. `watch_intents` and `opportunity_signals` carry no owner, and the watch/opportunity read and cancel endpoints are unscoped. Evaluation itself already fans out correctly — every active watch is evaluated independently and produces its own signal — so ownership is an additive change, not a redesign.
