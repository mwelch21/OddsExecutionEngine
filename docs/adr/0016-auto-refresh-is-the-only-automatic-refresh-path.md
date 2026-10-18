# ADR-016: Auto-Refresh is the only automatic refresh path

- Status: accepted
- Date: 2026-10-11

## Context

Until now refresh has been manual only: no scheduler, no timer, no background job. That rule is the main limit on spend under a 500-credit monthly plan. Notifications change the picture. A watch can only fire when its quotes are refreshed, so with refresh manual only, a notification arrives seconds after the operator's own click, and adds nothing. The operator wants refresh to run while they are away, but only when they choose, so spend stays deliberate.

## Decision

**Auto-Refresh** is an operator-controlled on/off switch, and the only path by which the system refreshes on its own. Manual refresh always works, whether Auto-Refresh is on or off.

- **Where it runs.** A Python `auto-refresh` worker, from the same image as the API with a different command. It calls the ingestion service in-process, with no HTTP hop. A Postgres advisory lock ensures only one refresh cycle runs at a time, however many workers start. It qualifies as its own process under ADR-013's rule: different runtime profile, and failure isolation from the API.
- **State.** A settings row in Postgres holds `enabled`, the interval and the quota floor. `GET/PUT /auto-refresh` exposes it (API parity), and the UI toggle calls it. State survives restarts exactly as last set.
- **Cadence: derived cooldown.**
  - The worker polls every 30s.
  - It finds the sports that have at least one active watch the evaluator will act on. Today that means the event has not started; the rule widens automatically once live events are evaluated.
  - It refreshes each such sport whose `last_refreshed_at + interval <= now`.
  - `last_refreshed_at` is stored per sport and updated by every sport-wide pull, manual or automatic. A per-event manual refresh does not update it, because it covered one event.
  - There is no stored `next_due_at`, no catch-up queue, and no overlapping refreshes.
  - The interval defaults to 5 minutes and the operator can set it from 1 to 60. It is a freshness target, not an SLA: upstream failures, slow calls or worker downtime can stretch the gap.
- **Cost when idle.** With no qualifying watches, a poll makes no upstream call. Leaving Auto-Refresh on costs nothing.
- **Out of credits.** When the provider reports `OUT_OF_USAGE_CREDITS`, Auto-Refresh stays **on** but **pauses**, and its status reports the pause. It resumes on its own when a later observation shows credits again (the monthly reset). Auto-Refresh never switches itself off. Other failed refreshes are logged, reported as the last outcome in `GET /auto-refresh`, and the next poll carries on.
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

## Consequences

- The "refresh is manual" rule becomes "manual, plus Auto-Refresh when the operator turns it on". CLAUDE.md and `conventions.md` are updated to match.
- New persisted state: the Auto-Refresh settings row, `last_refreshed_at` per sport, and the latest quota observation.
- When multiple users arrive (#14), Auto-Refresh becomes always-on and the switch goes away. The cooldown and quota rules carry over unchanged.
