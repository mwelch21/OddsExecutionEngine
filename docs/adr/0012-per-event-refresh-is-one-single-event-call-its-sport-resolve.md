# ADR-012: Per-event refresh is one single-event call, its sport resolved from what we already store

- Status: accepted
- Date: 2026-09-30

## Context

`POST /ingestion/quotes/refresh` located its event by pulling every sport in `ODDS_API_SPORTS` in turn. Billing is `[markets] x [regions]` credits per call, so refreshing one event cost 3 credits per configured sport — more than refreshing a whole sport, while storing a fraction of the data. `ODDS_API_SPORTS` was being held to one sport purely to bound that loop.

The Odds API has a dedicated `GET /v4/sports/{sport}/events/{eventId}/odds`, costing `[markets returned] x [regions]`. It needs the sport key up front.

## Decision

- Per-event refresh makes **one** upstream call, to the single-event endpoint.
- The sport key is resolved without a paid call: the stored `events.sport`/`league`, falling back to the provider's in-process event cache when nothing has stored a sport yet. The `(sport, league)` pair is matched against the provider's own catalog (`list_supported_sports`).
- Unknown event → `UnknownEventError` (404). Known event, unresolvable sport → `UnresolvableEventSportError` (422). Neither touches upstream. There is no fallback scan.
- The single-event pull is deliberate, so it is `live=True` through the provider cache (ADR-011): coalesced, never stale. Its cache key (`event:{sport}:{event_id}`) is separate from sport feeds.
- An upstream 404 on the single-event endpoint (event finished or pulled) yields no quotes rather than an error, matching the prior "not found in any feed" behaviour.
- `ODDS_API_SPORTS` is removed. Its only consumer was the scan loop. Settings ignore unknown env vars, so existing `.env` files keep working.

## Why

- resolving the key by catalog match, not by reconstructing it from the stored strings, means a guess can never reach upstream and buy a 404
- resolution runs before the ingestion workflow starts, so a caller mistake is not logged as an ingestion failure and costs nothing
- a stored row whose sport is `NULL` (an event first created by a bare per-event refresh) still resolves through the provider cache instead of failing

## Rejected alternatives

- **Reuse the sport feed from the cache** (the original plan for this ticket). Only works if someone recently refreshed that sport, and would serve a refresh stale data, which ADR-011 forbids.
- **Store the provider sport key on `events`.** Needs a migration for information already derivable from `sport`/`league` plus the catalog.
- **Fall back to scanning on resolution failure.** Reintroduces the cost bug silently, exactly when nobody is looking.
