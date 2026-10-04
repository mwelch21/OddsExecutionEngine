# ADR-008: One opportunity per watch, and the watch is terminal once it fires

- Status: accepted
- Date: 2026-09-07

## Context

An opportunity was one row per `(watch_intent_id, market_id, sportsbook)`, and a single evaluation pass staged one `OpportunityIdentified` per row. A watch fillable at five books produced five rows and five notifications in one pass. The dedup key meant each book emitted once ever, so the defect was breadth-per-notification, not repetition over time: the user got "good price here — and another there", when the question is who has the best price and where else it can be filled.

## Decision

Collapse an opportunity to one record per watch, holding `best_sportsbook` / `best_price` as columns and `matching_quotes` as JSON. Replace `uq_opportunities_identity` with `unique(watch_intent_id)`. Transition a watch that fires to `triggered`, which is terminal: it is excluded from later evaluation and never re-arms.

## Why

- a watch names exactly one market, so every fillable quote it matches is a competing book on that market, not a separate finding
- `execution_recommendations.ranked_quotes` already made this exact JSON-over-child-table call for the same shape, and `market_quotes_history` keeps analytics unblocked
- the system notifies but cannot place bets or observe whether the user acted; once the limit is met and reported, the job is done
- terminal watches remove themselves from the active set, so evaluation cost falls instead of growing without bound
- `unique(watch_intent_id)` states the real invariant; `(watch_intent_id, market_id)` would be strictly weaker and would permit a state that cannot legitimately occur

## Rejected alternatives

- **A child table for matching books**: same shape as `ranked_quotes`, which the repo already resolved in favour of JSON; adds a join for a list only ever read whole.
- **Re-arming a watch when its opportunity goes stale**: fillability is a bare `price >= target` comparison with no memory, so a price oscillating across the target would invalidate and re-fire repeatedly. It also makes "terminal" non-terminal, so "which of my watches fired?" stops being answerable.
- **Re-emitting when a further book later qualifies**: the user has most likely already acted; a late second alert is noise.
- **Live re-check of the book list on read**: merges "here is what we found" with "here is what is true now" and destroys the provenance. `is_valid` / `invalid_reason` carry the freshness separately.
- **Backfilling existing per-book rows**: grouping logic that runs exactly once, against test data nobody will miss, where any bug produces plausible-looking wrong history. Migration `20260515_0007` deletes them, and says so.

## Consequences

- `POST /watch-intents` can return a watch already `triggered` with its opportunity attached, because creation still evaluates immediately. Making the caller wait for an unrelated refresh to learn an already-known answer is worse; if it reads badly the fix is presentational. The create response therefore gains a nullable nested `opportunity`; every other watch read keeps the flat `WatchIntentResponse` shape.
- Cancelling a `triggered` watch is refused with 409. Not in the issue's acceptance criteria, but without it `DELETE` silently overwrites the terminal status and the lifecycle question this decision protects becomes unanswerable again.
- Staleness is judged against the best book alone (`get_latest_quote_times` keys on `best_sportsbook`). Accepted gap: a best book moving down while a listed second book overtakes it is reported as stale rather than silently re-ranked.
- Application-level dedup (`list_existing_opportunity_keys`, `existing_opportunity_keys`) is removed as structurally unreachable. The DB constraint remains the real guard and covers concurrent double-evaluation, which key checking never did reliably.
- Re-watching a market becomes an explicit user action creating a new watch with a new id. Not yet implemented.
