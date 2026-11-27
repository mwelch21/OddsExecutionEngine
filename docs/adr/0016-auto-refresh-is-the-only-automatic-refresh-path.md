# ADR-016: Auto-Refresh is the only automatic refresh path

- Status: accepted
- Date: 2026-10-11
- Amended: 2026-11-27 (#128): the candidate rule follows event status and watch window, and live sports get a second interval
- Amended: 2026-11-27 (#132): an operator-set sport focus narrows the candidates

## Context

Until now refresh has been manual only: no scheduler, no timer, no background job. That rule is the main limit on spend under a 500-credit monthly plan. Notifications change the picture. A watch can only fire when its quotes are refreshed, so with refresh manual only, a notification arrives seconds after the operator's own click, and adds nothing. The operator wants refresh to run while they are away, but only when they choose, so spend stays deliberate.

## Decision

**Auto-Refresh** is an operator-controlled on/off switch, and the only path by which the system refreshes on its own. Manual refresh always works, whether Auto-Refresh is on or off.

- **Where it runs.** A Python `auto-refresh` worker, from the same image as the API with a different command. It calls the ingestion service in-process, with no HTTP hop. A Postgres advisory lock ensures only one refresh cycle runs at a time, however many workers start. It qualifies as its own process under ADR-013's rule: different runtime profile, and failure isolation from the API.
- **State.** A settings row in Postgres holds `enabled`, the two intervals and the quota floor. `GET/PUT /auto-refresh` exposes it (API parity), and the UI toggle calls it. State survives restarts exactly as last set.
- **Cadence: derived cooldown.**
  - The worker polls every 30s.
  - It finds the **candidate** sports: those with at least one active, unexpired watch the evaluator will act on (amended 2026-11-27, #128). `AutoRefreshCandidateEngine` holds the rule:
    - a `pre_game` or `full_game` watch on an `upcoming` event, or
    - a `live` or `full_game` watch on a `live` event.

    An `ended` event never counts. The rule reads the stored event status (ADR-019) and the watch window (ADR-017), not the start time as a live signal. The start time matters in one case only, the evaluator's own: a `pre_game` window closes once the stored start has passed, even on an event still stored `upcoming`, so it is not a candidate. A `full_game` watch on such an event stays one, because the pull is what observes kickoff.
  - **Two intervals, both operator-set** (amended 2026-11-27, #128). A candidate sport with any candidate watch on a `live` event is due on `live_interval_minutes`; every other one on `interval_minutes` (the upcoming interval). Both are global: one live interval covers every live game.
  - **Sport focus narrows the candidates** (amended 2026-11-27, #132). The settings row holds `sport_focus`, a set of catalog sport keys (`GET /api/v1/sports`), stored sorted and de-duplicated. With a non-empty focus, a candidate sport outside it is dropped, even when it has qualifying watches. The focus never adds a sport: a focused sport with no qualifying watch is still not refreshed. An empty focus, the default, narrows nothing. `AutoRefreshCandidateEngine.focus` holds the rule. A key outside the catalog is rejected (422) when the settings are saved. Manual refresh ignores the focus. The status reports `watched_sports` (the candidates before the focus) and `excluded_sports` (dropped by it), both from stored watches and the local catalog, never from the provider. The events view reads the stored focus from this operator route; once auth (#14) enforces `require_operator`, a non-operator's events view falls back to all sports until the focus is exposed on a public read.
  - It refreshes each candidate sport whose `last_refreshed_at + its interval <= now`.
  - `last_refreshed_at` is stored per sport and updated by every sport-wide pull, manual or automatic. A per-event manual refresh does not update it, because it covered one event.
  - There is no stored `next_due_at`, no catch-up queue, and no overlapping refreshes.
  - Each interval defaults to 5 minutes and the operator can set it from 1 to 60. The live default is a fixed 5, not a copy of the upcoming interval. One rollout effect: the migration gives an existing settings row a live interval of 5 whatever its upcoming interval. On an install whose upcoming interval is above 5, a live sport's cooldown is therefore shorter than the configured upcoming cooldown right after the upgrade, until the operator moves the Live slider. An interval is a freshness target, not an SLA: upstream failures, slow calls or worker downtime can stretch the gap.
  - Settings are read on every poll, so a changed interval applies from the next poll with no restart.
- **Speed-up is manual** (#128). The free feed carries no game clock or period, so the system never changes an interval by itself. The operator speeds live refresh up, and back down, by moving the Live slider. A per-game boost or an elapsed-time rule is out of scope.
- **Status follows the pull** (#128). A sport-wide pull is what moves an event from `live` to `ended` (ADR-019), which expires its watches (ADR-017). So the last live pull of a game also stops further pulls for it.
- **Cost when idle.** With no qualifying watches, a poll makes no upstream call. Leaving Auto-Refresh on costs nothing.
- **Out of credits.** When the provider reports `OUT_OF_USAGE_CREDITS`, Auto-Refresh stays **on** but **pauses**, and its status reports the pause. While paused, the free balance check runs at most once per upcoming interval, whatever the live interval. It resumes on its own when a later observation shows credits again (the monthly reset). Auto-Refresh never switches itself off. Other failed refreshes are logged, reported as the last outcome in `GET /auto-refresh`, and the next poll carries on.
- **Quota observations and the quota warning.**
  - Every upstream call, manual or automatic, records its quota observation: remaining and used credits from the provider headers, or the local `markets × regions` count when headers are absent.
  - A `quota.warning.v1` public event (ADR-014) is written when remaining credits cross below the floor (previous ≥ floor > now). It re-arms once remaining is back above the floor.
  - The floor defaults to 10% of the plan (used + remaining, so 50 on the free tier) and is set in the same settings row.

## Why

- Spend stays an explicit operator choice: nothing pulls upstream unless the switch is on and a watch can use the result.
- The derived cooldown keeps every refreshed sport within about one interval of fresh, while a manual pull still saves the next automatic one. A fixed sweep that skips recently pulled sports would let gaps grow to nearly twice the interval.
- The advisory lock makes the at-most-one-cycle guarantee independent of how many processes are started.

## Rejected alternatives

- **A thread in the API process:** every API worker would tick, spending credits twice over unless it is fenced off separately.
- **Ticking from the Go notifier:** outside its delivery-only scope (ADR-013), and it would need an HTTP hop back into Python.
- **A fixed sweep that skips recently pulled sports:** worst-case gap of nearly two intervals.
- **Turning the switch off on a credit floor or at zero:** the operator chose a warning, not an automatic stop.
- **Keeping `starts_at > now` as the candidate rule:** every sport whose only watched event had started dropped out at kickoff, so a live watch could fire only on a manual refresh (#128).
- **A sport focus that adds sports, or a separate focus per surface** (#132): a pick that adds a sport without a qualifying watch spends credits nothing can use. One stored focus drives both Auto-Refresh and the events view's default filter, so the operator sets it once; the events view can still show all sports without changing it.
- **Automatic live speed-up (game clock, elapsed time, per-game boost):** the free feed has no signal for it, and spend must stay the operator's choice. 1 minute live costs 180 credits per sport per hour; 5 minutes costs 36.

## Consequences

- The "refresh is manual" rule becomes "manual, plus Auto-Refresh when the operator turns it on". CLAUDE.md and `conventions.md` are updated to match.
- The sport focus caps automatic spend to the picked sports: about 3 credits per focused, watched sport per pull (#132).
- New persisted state: the Auto-Refresh settings row (with its sport focus, #132), `last_refreshed_at` per sport, and the latest quota observation.
- When multiple users arrive (#14), Auto-Refresh becomes always-on and the switch goes away. The cooldown and quota rules carry over unchanged.
