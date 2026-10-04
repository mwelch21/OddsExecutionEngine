# ADR-011: A deliberate refresh always pulls live; the cache only collapses simultaneity

- Status: accepted
- Date: 2026-09-23

## Context

`PROVIDER_CACHE_TTL_SECONDS` shipped with ADR-009 as configuration ahead of the cache that would consume it, and sat unconsumed. Meanwhile the real cost became clear: The Odds API bills **credits, not requests** — `cost = [markets] x [regions]` per call — so the default configuration spends three credits every time a sport is pulled, and every refresh buys its own private copy of a pull that lands in one shared table.

The obvious fix was a minimum-age floor: inside some window, serve the cached response instead of calling upstream. That is wrong for this product. The case that matters is someone watching a live game who sees a play happen and hits refresh: they need the line as of that click, not the line from the moment before it. A floor answers that request with the pre-play price, which is precisely the number they are refreshing to escape.

## Decision

A deliberate refresh (`POST /ingestion/quotes/refresh-sport`) **always** pulls live. The cache serves two narrower purposes:

- **Single-flight coalescing.** Concurrent refreshes for the same sport share one upstream call. This is not stale-serving: a caller that queues behind an in-flight load is served by a load that finished *after* it arrived.
- **Incidental reuse.** `TheOddsApiProvider.list_quotes` walks every configured sport to locate one event. Those repeats honour `PROVIDER_CACHE_TTL_SECONDS`. (Superseded by ADR-012: per-event refresh is now a deliberate single-event pull; incidental reuse remains for `list_events_for_sport`.)

Acceptance keys on a **load generation counter**, not on comparing timestamps. A live caller records the generation present on arrival and will only accept an entry from a strictly later load.

No minimum-age floor ships, not even disabled by default.

## Why

- the freshness a refresh button promises is the whole reason the button exists; a cache that quietly breaks that promise is worse than no cache
- coalescing gets the double-click protection a floor was wanted for, without ever handing anyone a price older than their own click
- comparing `loaded_at >= arrived_at` is ambiguous when both readings fall in the same clock tick — under a coarse clock a refresh accepts an entry older than itself. A counter answers "did a load finish after I arrived" exactly, at any clock resolution. This was a real bug, caught by a frozen-clock test
- the fetch report is returned, not stashed on the provider: one provider instance serves every request thread, since all handlers are sync and Starlette runs them in a threadpool
- quota reads before `raise_for_status`, because a rejected call still spent credits

## Rejected alternatives

- **Minimum-age floor.** Serves a pre-play price to a post-play refresh. Rejected on the product case above.
- **A floor shipped defaulted to `0`.** Dead configuration for behaviour ruled out; a knob whose only correct setting is "off" is a trap for a future reader.
- **Stateful `provider.last_report()`.** Racy: two concurrent refreshes for different sports clobber each other's report.
- **Caching `(payload, quota)` together.** A cache hit would replay the earlier call's credit figures as though current. Quota is captured in a per-call closure and reported only when the loader actually ran.
- **An optional `quota_sink` out-parameter** to avoid updating 17 test patch sites. A worse API forever in exchange for a one-off mechanical edit.

## Consequences

- The saving is on simultaneity, not sequence. Two users refreshing thirty seconds apart still cost two calls, and should. This is a smaller win than a floor would give, and the correct one.
- `PROVIDER_CACHE_TTL_SECONDS` finally has a consumer, and governs only the incidental path. `0` still disables reuse, as published.
- `list_quotes_for_sport` returns `(quotes, ProviderFetchReport)`; `refresh_sport` returns a `SportRefreshResult`. The router no longer assembles the sport/count wrapper itself.
- `SportRefreshResponse` reports `upstream_contacted`, `data_age_seconds`, `credits_spent` and `credits_remaining`. Credit nulls mean "not reported", never zero.
- The cache is per-process. When #30 moves it to Redis, whether coalescing becomes cross-process is a decision for that ticket.
