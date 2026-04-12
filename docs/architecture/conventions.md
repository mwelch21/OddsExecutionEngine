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

## Stage 3 landing zones

- Domain event types should live in `backend/app/domain/events.py` or an adjacent `domain/events/` package.
- Publisher ports should live in `backend/app/application/ports.py` or an adjacent application ports module.
- Publisher adapters should live under `backend/app/infrastructure/publishers`.
- `workflow_events` schema ownership belongs to stage 3 migrations under `backend/db/migrations`.

## Decisions log policy

- Add a decision entry when changing migration strategy, schema ownership, persistence layout, layer boundaries, event model boundaries, or other major architectural rules.
- Add to conventions when the rule is general and expected to remain true across features.
- Update both docs when a large change introduces both a one-time decision and a standing rule.
