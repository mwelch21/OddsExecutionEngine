# ADR-014: Public events are versioned CloudEvents in their own outbox

- Status: accepted
- Date: 2026-10-04

## Context

Events now leave the system: Web Push today, and a webhook or SDK for programmatic consumers later. Internal `workflow_events` are an audit trail shaped for this codebase. They have no version, they rely on implicit meanings (`aggregate_id` is the opportunity id), and they lack what an outside reader needs: who is playing, when, and how old the price is. Exposing them would freeze internal shapes as a public contract, and the Go notifier (ADR-013) would have to understand Python's domain.

## Decision

Public events are a separate, versioned contract, written to their own outbox.

- **Separate outbox.** When a domain transaction stages an internal event that has a public counterpart, Python writes the public event in the **same transaction** to a public outbox table. Consumers outside the Python app, starting with the notifier, read only the public outbox.
- **Envelope.** CloudEvents 1.0 (`id`, `source`, `type`, `specversion`, `time`, `subject`, `data`, `dataschema`). The version is part of `type`, for example `oddsengine.opportunity.identified.v1`.
- **Public set.** Nothing is public by default. v1 has two types:
  - `oddsengine.opportunity.identified.v1`: `opportunity_id`, `watch_intent_id`, `event {id, sport, league, home, away, starts_at}`, `market_type`, `selection`, `line`, `target_price`, `best {sportsbook, price, quoted_at}`, `matching [{sportsbook, price}]`. `quoted_at` is the book's clock (ADR-009). A live/pre-game phase field is added as optional once event status exists.
  - `oddsengine.quota.warning.v1`: `remaining`, `used`, `floor`, `observed_at`. Emitted once per crossing below the floor, not on every refresh. This is a new domain event; there was no internal counterpart.
- **Rendering belongs to the channel.** The public event is pure data. The notifier renders the Web Push title, body and URL from it (the payload limit is 4 KB). A future webhook sends the event itself.
- **Compatibility.** Adding a field keeps the version. Removing a field or changing its meaning is a new type (`.v2`), emitted alongside `.v1` for a deprecation window. Schemas live as JSON Schema files under `contracts/events/`, and Python and Go contract tests validate against them.

## Rejected alternatives

- **The notifier reads `workflow_events` and maps them itself:** Go would need to know internal schemas, and every internal refactor would risk breaking delivery.
- **Mapping to public events after commit:** a crash between commit and mapping loses the public event. The same-transaction write keeps the two outboxes consistent.
- **A custom envelope:** CloudEvents costs nothing extra, has Go and Python SDKs, and is what webhook consumers already expect.
- **A `display` block in the public event:** mixes one channel's presentation into a contract every channel shares.

## Consequences

- Two outboxes: `workflow_events` stays the internal audit trail, and the public outbox is what leaves the system. Publish state and relay work for external delivery belong on the public outbox.
- Adding a public event type is a deliberate act: a schema file, a mapping, and contract tests.
- ADR-013's transport now reads the public outbox.
