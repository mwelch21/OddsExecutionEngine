# ADR-019: Event status is observed from feed presence, and live lines can fill

- Status: accepted
- Date: 2026-11-27

## Context

The provider returns in-play events alongside upcoming ones, and ingestion stored all of them. Three rules then hid the live data:

- `GET /events` excluded every started event by default.
- Watch evaluation skipped every started event (`watch_evaluation.skipped_event_started`), so a live event could never produce an opportunity.
- `events.status` existed with a default of `upcoming`, and no code wrote it. "Started" was inferred from `starts_at` alone, so a game in its second quarter and a game that finished three hours ago looked the same.

The conventions stated the rule behind all three: "a started event can no longer produce an opportunity". That is true for a pre-game line. It is false for a live line, and live markets are where fill windows are shortest.

## Decision

This ADR reverses the "started events can never fill" rule.

- **Status source: feed presence.** It costs no extra credits.
  - A sport-wide pull writes `upcoming` for each offered event that has not started, and `live` for each offered event that has started.
  - A started, stored, not-ended event of that sport that the pull did not offer becomes `ended`. An unstarted event that is missing stays as stored: absence before kickoff proves nothing.
  - A per-event refresh that the provider answers with a 404 or no event writes `ended`. One that finds the event writes `upcoming` or `live` from its start time.
  - No `/scores` call. Moving to `/scores` on a paid plan is #127.
- **The start time alone never sets status.** An event stored `upcoming` whose start has passed has not been observed since kickoff. It is listed as neither upcoming nor live until a refresh settles it.
- **Line phase.** Each stored quote (`market_quotes_latest`, `market_quotes_history`) carries `phase`: `pre_game` or `live`, from the event status when it was pulled. The two clocks (`quoted_at`, `ingested_at`) keep their meaning; phase is not a clock.
- **What a watch may fill on.** One pure rule, `EventStatusEngine.fillable_quotes`:
  - `ended`: nothing. Evaluation logs `watch_evaluation.skipped` with `reason=event_ended`.
  - `live`: live lines only. A pre-game row that a book left behind at kickoff is a price nobody can take.
  - `upcoming`: every stored line.
- **Browse filter.** `GET /api/v1/events` takes `status` = `upcoming` | `live` | `all` (`all` is upcoming plus live; the default). Ended events are never listed. `include_started` stays as a deprecated alias (`true` reads as `all`, `false` as `upcoming`), so v1 stays additive (ADR-018). An explicit `status` wins over the alias.

## Rejected alternatives

- **Infer live from `starts_at`:** reports a finished game as live.
- **Call `/scores` for status:** extra credits on every refresh. Deferred to #127.
- **Mark every missing event ended:** an event that a book has not listed yet would end before it starts.
- **Backfill stored events' status in the migration:** whether an old started event is live or ended was never observed. The migration backfills only line phase, from facts it holds: a line pulled at or after its event's start came from a feed that still offered the event.

## Consequences

- #10 can build watch windows (ADR-017) on observed status and line phase.
- Interim gap until #10: a watch created before kickoff stays armed after kickoff and can fire on a live line. ADR-017's `pre_game` window, which expires at `event_started`, closes this.
- An event stays `live` until a pull of its sport no longer offers it. Its quotes' `last_ingested_at` shows how old that observation is.
- Auto-Refresh's candidate rule is unchanged (#128).
