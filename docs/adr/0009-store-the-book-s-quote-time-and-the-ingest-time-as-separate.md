# ADR-009: Store the book's quote time and the ingest time as separate columns

- Status: accepted
- Date: 2026-09-12

## Context

`market_quotes_latest.quoted_at` / `market_quotes_history.quoted_at` held one value: the moment ingestion pulled the row. The provider's own per-book `last_update` was read past and discarded. A line a sportsbook had not touched in three days, pulled ten seconds ago, was stored — and would be read — as ten seconds old. With refresh hand-driven and infrequent, that is the difference between a number you can act on and one you cannot.

## Decision

Split the two facts across two columns on both quote tables. `ingested_at` is when we pulled, always known, `NOT NULL`. `quoted_at` keeps its name but now means what it says: when the sportsbook last moved the line, taken from the provider. It is nullable, and `NULL` means the provider exposes no such time. Domain `Quote` carries both, with `line_age_known` and `effective_quoted_at` defining the fallback in one place.

## Why

- a quote's age is a property of the book's line, not of our polling schedule; conflating them makes every quote look as fresh as the last refresh
- `NULL` for "provider exposes no time" keeps unknown age distinguishable from freshly moved. A stamped fallback in the column would be indistinguishable from a real observation the moment it was written
- the fallback to ingest time still exists, but as a derived read (`effective_quoted_at`), so the stored data never asserts a line movement nobody observed
- The Odds API reports `last_update` at both bookmaker and market level, so the data was already on the wire and only needed keeping

## Rejected alternatives

- **Rename `quoted_at` to `ingested_at` and add `line_moved_at`**: one column for the pull time and a new name for the book's time. Same information, but `quoted_at` is the natural name for the book's own quote time and giving it to the pull time is what caused the confusion in the first place.
- **`NOT NULL quoted_at` backfilled from ingest time**: makes every provider look like it reports line movement, which is the defect restated in two columns.
- **A separate `line_age_known` boolean**: derivable from `quoted_at IS NULL`, so it is a second source of truth for one fact.
- **Keeping old rows' `quoted_at` values on migration**: those values were pull times. Left in a column that now means line movement they would assert movements that were never observed, so `20260912_0008` moves them to `ingested_at` and nulls `quoted_at`.

## Consequences

- Opportunity staleness (`get_latest_quote_times`) keys on `ingested_at`, not `quoted_at`. The question it answers is whether a later pull replaced the row the opportunity was cut from; keying on the book's time would report every unknown-age book as `quote_removed`. Validity behaviour is otherwise unchanged.
- `OPPORTUNITY_TTL_MINUTES` defaults to 720 (12h) instead of 5. Nothing refreshes on a schedule, so a minutes-long TTL marked every opportunity invalid before a human could read it, and the flag degraded into noise. Tighten it once a scheduler lands.
- `PROVIDER_CACHE_TTL_SECONDS` is introduced as configuration ahead of the provider cache that consumes it. `0` disables reuse.
- The API surface is unchanged: both times reach the domain `Quote`, but no response schema exposes them yet.
