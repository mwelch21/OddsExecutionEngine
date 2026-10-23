# ADR-010: Event browse reads go through a read-only unit of work

- Status: accepted
- Date: 2026-09-13

## Context

Every persistence seam in the system so far is a write unit of work: it stages domain events, persists them in the same transaction as the domain writes, and publishes after commit. `GET /events` needs none of that. It answers a question and changes nothing, but it still needs a session, a transaction boundary, and the same layering discipline as the write paths — the application layer must not import SQLAlchemy, and the route must stay thin.

## Decision

Introduce `EventReadUnitOfWork` / `EventReadUnitOfWorkFactory` in `backend/app/application/ports.py` as a distinct, read-only seam. It has `__enter__` / `__exit__`, `count_events`, and `list_events`, and deliberately has no `stage_event` and no `committed_events`. Its `__exit__` rolls back and closes: there is nothing to commit. `EventQueryService` depends only on that port, and `SqlAlchemyEventReadUnitOfWork` implements it under `infrastructure/persistence`.

## Why

- a read path that cannot stage an event cannot accidentally emit one; the missing methods are the guarantee, not a convention
- reusing a write unit of work here would hand the read path a `stage_event` it must be trusted never to call, and a commit boundary with nothing to commit
- filtering and paging belong in SQL, which requires a real session behind the port; returning raw rows to the service would leak the schema into the application layer
- the service takes `now` once and passes it to both `count_events` and `list_events`, so the total and the page can never disagree about which events have started

## Rejected alternatives

- **Extend `WatchIntentUnitOfWork` with event listing**: it already reads events (`get_event_starts_at`), but it is a write seam carrying watch lifecycle transitions and event staging. Browsing events is not watch work, and joining them makes a divergent-change magnet.
- **Query directly from the service with a session**: violates `api -> application -> domain` with infrastructure behind ports, and puts SQLAlchemy imports in the application layer.
- **Filter and page in Python after loading rows**: the reason this endpoint is page-based is that "page 2 of 7" must be renderable. Dropping started events after the query reports a total the returned page does not add up to.
- **Cursor pagination**: the set is small, slow-moving, and sorted by start time. Cursors buy stability under heavy churn that this data does not have, and cannot render a page count.

## Consequences

- The read seam is the template for later read endpoints (`GET /events/{id}/markets`, `GET /events/{id}/quotes`), which should extend it rather than reach for a write unit of work. `GET /events/{id}/quotes` now does exactly that: it added `get_event` and `list_market_quotes` to this port rather than introducing a second seam, and ranking stayed in the application layer so the engine rule is not duplicated in SQL.
- Per-event freshness is computed in one grouped aggregate over `market_quotes_latest`, reported as two independent facts: `last_ingested_at` (`MAX(ingested_at)`, our pull) and `oldest_line_quoted_at` (`MIN(quoted_at)`, the books'). ADR-009's split is what makes reporting them separately possible.
- Book counts are `COUNT(DISTINCT sportsbook)`, never row counts. `market_quotes_latest` is keyed `(market_id, sportsbook)`, so one book quoting both sides of three markets is six rows and one book; counting rows would report six unknown-age "books" for a single silent provider.
- Known gap, accepted: ingestion only replaces the `(market_id, sportsbook)` rows present in a pull, so a line a book has stopped offering keeps its latest row. `MIN(quoted_at)` can therefore be dragged older by a market that is no longer live. Pruning retired rows changes ingestion semantics for the recommendation and watch paths too, so it belongs to its own ticket.
