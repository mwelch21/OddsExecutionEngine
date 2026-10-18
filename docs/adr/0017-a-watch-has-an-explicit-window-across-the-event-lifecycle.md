# ADR-017: A watch has an explicit window across the event lifecycle

- Status: accepted
- Date: 2026-10-11

## Context

Watches had one expiry, a TTL, and evaluation silently skipped any event that had started. Live lines are about to become actionable (#38), which raises a question the model could not answer: does a watch made before the game still apply once it is under way? A watch only stores a target price, and the same number means a different bet in each phase. Before the game, "+120" is a judgement on the matchup. Live, "+120" can appear because the team is losing. Without an explicit answer, a pre-game watch would silently fire on a live line its author never meant.

## Decision

- **Watch window.** Every watch carries an explicit window, always stored:
  - `pre_game`: fires on pre-game lines only, and expires when the event starts
  - `live`: fires on live lines only (pre-game lines are ignored), and expires when the event ends
  - `full_game`: fires on either, and expires when the event ends

  The TTL still applies on top of every window.
- **Default.** When a watch is created without a window, one domain policy supplies it from the event's status at creation: `upcoming` gives `pre_game`, and `live` gives `live`. The API accepts an optional `window`. The policy is the only place the default lives, so a future operator or user preference changes the policy's input, never the watch model or existing watches.
- **Event end.** When the event is `ended` (or cancelled, if #38 surfaces it), every remaining active watch expires, whatever its window or TTL.
- **Expiry reason.** Expired watches and `WatchIntentExpired` record `expired_reason`: `ttl`, `event_started`, `event_ended` or `event_cancelled`.
- **When.** Lifecycle expiry happens when ingestion observes the status change, in the same transaction as the status write. Evaluation re-checks it as a backstop, because an event that is never refreshed after its start would otherwise leave its watches active forever.
- **Visibility, not noise.** Lifecycle expiry sends no notification. The User view shows each expired watch and why.
- **Live opportunities.** `opportunity.identified.v1` carries `phase: pre_game | live`, and the notifier prefixes live notifications with `LIVE ·`.

## Rejected alternatives

- **Every watch expires at start:** blocks the deliberate case of watching a price through the game.
- **Every watch stays armed into live:** silently fires pre-game intent on live prices.
- **Deriving the window on every evaluation instead of storing it:** a change of default would retroactively change what existing watches mean.
- **Notifying on lifecycle expiry:** a push about something that did not happen. It can come later as a "target still unfilled" signal.

## Consequences

- Watch evaluation must tell a live line from a pre-game line. #38's requirement that the two be distinguishable becomes load-bearing.
- #10 (lifecycle expiry) is specified by this ADR and still depends on event status from #38.
