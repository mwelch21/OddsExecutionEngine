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

## ADR-007: Stage 4 uses minimal canonical quote normalization

- Status: accepted
- Date: 2026-04-12

### Context

Stage 4 introduces the first quote ingestion workflow. The repo already has a canonical `Quote` model and market identity rules, but no separate raw-provider schema layer yet.

### Decision

Use a minimal normalization step that filters provider data directly into canonical `Quote` values and persists them through the existing market identity and latest/history quote tables.

### Why

- keeps stage 4 focused on the ingestion workflow instead of expanding provider modeling prematurely
- reuses the deterministic `Quote` shape already consumed by recommendation logic
- keeps the mock-provider implementation simple and testable

### Rejected alternatives

- introduce richer raw-provider models now: extra scope before multiple providers exist
- persist provider payloads directly without normalization: weakens deterministic ingestion boundaries

### Consequences

- stage 4 providers must produce data that can normalize into canonical `Quote` values
- richer provider metadata can be added later without replacing the first ingestion boundary

## ADR-008: One opportunity per watch, and the watch is terminal once it fires

- Status: accepted
- Date: 2026-09-07

### Context

An opportunity was one row per `(watch_intent_id, market_id, sportsbook)`, and a single evaluation pass staged one `OpportunityIdentified` per row. A watch fillable at five books produced five rows and five notifications in one pass. The dedup key meant each book emitted once ever, so the defect was breadth-per-notification, not repetition over time: the user got "good price here — and another there", when the question is who has the best price and where else it can be filled.

### Decision

Collapse an opportunity to one record per watch, holding `best_sportsbook` / `best_price` as columns and `matching_quotes` as JSON. Replace `uq_opportunities_identity` with `unique(watch_intent_id)`. Transition a watch that fires to `triggered`, which is terminal: it is excluded from later evaluation and never re-arms.

### Why

- a watch names exactly one market, so every fillable quote it matches is a competing book on that market, not a separate finding
- `execution_recommendations.ranked_quotes` already made this exact JSON-over-child-table call for the same shape, and `market_quotes_history` keeps analytics unblocked
- the system notifies but cannot place bets or observe whether the user acted; once the limit is met and reported, the job is done
- terminal watches remove themselves from the active set, so evaluation cost falls instead of growing without bound
- `unique(watch_intent_id)` states the real invariant; `(watch_intent_id, market_id)` would be strictly weaker and would permit a state that cannot legitimately occur

### Rejected alternatives

- **A child table for matching books**: same shape as `ranked_quotes`, which the repo already resolved in favour of JSON; adds a join for a list only ever read whole.
- **Re-arming a watch when its opportunity goes stale**: fillability is a bare `price >= target` comparison with no memory, so a price oscillating across the target would invalidate and re-fire repeatedly. It also makes "terminal" non-terminal, so "which of my watches fired?" stops being answerable.
- **Re-emitting when a further book later qualifies**: the user has most likely already acted; a late second alert is noise.
- **Live re-check of the book list on read**: merges "here is what we found" with "here is what is true now" and destroys the provenance. `is_valid` / `invalid_reason` carry the freshness separately.
- **Backfilling existing per-book rows**: grouping logic that runs exactly once, against test data nobody will miss, where any bug produces plausible-looking wrong history. Migration `20260515_0007` deletes them, and says so.

### Consequences

- `POST /watch-intents` can return a watch already `triggered` with its opportunity attached, because creation still evaluates immediately. Making the caller wait for an unrelated refresh to learn an already-known answer is worse; if it reads badly the fix is presentational. The create response therefore gains a nullable nested `opportunity`; every other watch read keeps the flat `WatchIntentResponse` shape.
- Cancelling a `triggered` watch is refused with 409. Not in the issue's acceptance criteria, but without it `DELETE` silently overwrites the terminal status and the lifecycle question this decision protects becomes unanswerable again.
- Staleness is judged against the best book alone (`get_latest_quote_times` keys on `best_sportsbook`). Accepted gap: a best book moving down while a listed second book overtakes it is reported as stale rather than silently re-ranked.
- Application-level dedup (`list_existing_opportunity_keys`, `existing_opportunity_keys`) is removed as structurally unreachable. The DB constraint remains the real guard and covers concurrent double-evaluation, which key checking never did reliably.
- Re-watching a market becomes an explicit user action creating a new watch with a new id. Not yet implemented.

## ADR-009: Store the book's quote time and the ingest time as separate columns

- Status: accepted
- Date: 2026-09-12

### Context

`market_quotes_latest.quoted_at` / `market_quotes_history.quoted_at` held one value: the moment ingestion pulled the row. The provider's own per-book `last_update` was read past and discarded. A line a sportsbook had not touched in three days, pulled ten seconds ago, was stored — and would be read — as ten seconds old. With refresh hand-driven and infrequent, that is the difference between a number you can act on and one you cannot.

### Decision

Split the two facts across two columns on both quote tables. `ingested_at` is when we pulled, always known, `NOT NULL`. `quoted_at` keeps its name but now means what it says: when the sportsbook last moved the line, taken from the provider. It is nullable, and `NULL` means the provider exposes no such time. Domain `Quote` carries both, with `line_age_known` and `effective_quoted_at` defining the fallback in one place.

### Why

- a quote's age is a property of the book's line, not of our polling schedule; conflating them makes every quote look as fresh as the last refresh
- `NULL` for "provider exposes no time" keeps unknown age distinguishable from freshly moved. A stamped fallback in the column would be indistinguishable from a real observation the moment it was written
- the fallback to ingest time still exists, but as a derived read (`effective_quoted_at`), so the stored data never asserts a line movement nobody observed
- The Odds API reports `last_update` at both bookmaker and market level, so the data was already on the wire and only needed keeping

### Rejected alternatives

- **Rename `quoted_at` to `ingested_at` and add `line_moved_at`**: one column for the pull time and a new name for the book's time. Same information, but `quoted_at` is the natural name for the book's own quote time and giving it to the pull time is what caused the confusion in the first place.
- **`NOT NULL quoted_at` backfilled from ingest time**: makes every provider look like it reports line movement, which is the defect restated in two columns.
- **A separate `line_age_known` boolean**: derivable from `quoted_at IS NULL`, so it is a second source of truth for one fact.
- **Keeping old rows' `quoted_at` values on migration**: those values were pull times. Left in a column that now means line movement they would assert movements that were never observed, so `20260912_0008` moves them to `ingested_at` and nulls `quoted_at`.

### Consequences

- Opportunity staleness (`get_latest_quote_times`) keys on `ingested_at`, not `quoted_at`. The question it answers is whether a later pull replaced the row the opportunity was cut from; keying on the book's time would report every unknown-age book as `quote_removed`. Validity behaviour is otherwise unchanged.
- `OPPORTUNITY_TTL_MINUTES` defaults to 720 (12h) instead of 5. Nothing refreshes on a schedule, so a minutes-long TTL marked every opportunity invalid before a human could read it, and the flag degraded into noise. Tighten it once a scheduler lands.
- `PROVIDER_CACHE_TTL_SECONDS` is introduced as configuration ahead of the provider cache that consumes it. `0` disables reuse.
- The API surface is unchanged: both times reach the domain `Quote`, but no response schema exposes them yet.
