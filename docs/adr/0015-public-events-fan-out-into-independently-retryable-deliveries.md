# ADR-015: Public events fan out into independently retryable deliveries

- Status: accepted
- Date: 2026-10-11

## Context

The notifier (ADR-013) reads the public outbox (ADR-014). One public event goes to every destination the operator has: an iPhone, an iPad, later a webhook. One destination can succeed while another fails, so the unit of delivery is an event × destination, not an event. The notifier may run as more than one instance, may crash mid-send, and may be down while events accumulate.

Invariant: every intended destination gets an independently retryable delivery record, and no event is lost because a worker crashes or another transaction commits out of order.

## Decision

- **Two tables.** The public outbox row (`id`, `type`, `payload`, `created_at`, `dispatched_at`) and a `deliveries` table (`event_id`, `destination_id`, `status`, `attempts`, `next_attempt_at`, `locked_until`, `claim_token`, `delivered_at`, `last_error`).
- **Fan-out.** The notifier expands each undispatched outbox row into one delivery per active destination, then sets `dispatched_at`. A targeted event (`destination.test.v1`) expands into exactly one delivery, for the destination named in its `subject`, and goes through the same claim and send path as any other. `dispatched_at` means fan-out is complete, never "delivered". Delivery rows are created idempotently under `UNIQUE(event_id, destination_id)`, so a fan-out interrupted by a crash can be redone safely.
- **Claiming.** `FOR UPDATE SKIP LOCKED` stops two workers from claiming the same row at once. A lease (`locked_until`) lets another worker recover a claim after a crash. Each claim writes a fresh `claim_token`, and recording a result requires the token to still match. This fencing stops a worker whose lease expired from overwriting a newer worker's result. The claim transaction commits **before** the network call to the push service.
- **Outcomes.** 2xx → `delivered`. 404/410 → `gone`: the destination is soft-disabled (`disabled_reason = gone`) and its other pending deliveries become `gone`. Other 4xx → `failed` (permanent). 429, 5xx and network errors → retried with exponential backoff and jitter.
- **Max age.** Each public event type has a max age: an opportunity's is its validity TTL, a quota warning's is 24h, and a destination test's is 10 minutes. A delivery past max age becomes `expired` without being sent. This covers both give-up after retries and the backlog left by a notifier that was down.
- **Ordering.** No ordering is guaranteed across deliveries. A type that ever needs ordering carries a domain timestamp or version in its data (for example `best.quoted_at`), never delivery order.
- **Dedupe.** At-least-once. Consumers dedupe on the public event `id`. The Web Push `Topic` header only replaces a message the device has not yet received; it is not deduplication.
- **Waking.** `LISTEN/NOTIFY` on new outbox rows, plus a 30s safety sweep for missed notifications and retries that have come due. This is internal database work and spends no upstream credits.

## Rejected alternatives

- **A single published flag on the outbox row:** cannot represent one destination succeeding while another fails.
- **A per-consumer cursor on a sequence number:** Postgres assigns sequence values at insert but rows become visible at commit, so a cursor can permanently skip a slow transaction's row.
- **Holding the row lock across the network call:** ties database transactions to the push service's latency, and a hung call blocks the row indefinitely.
- **Python-side publish state and a relay on `workflow_events`:** superseded. `workflow_events` is the internal audit trail, and recovery belongs to the deliveries model.

## Consequences

- A webhook is a new channel whose destinations get delivery rows. The outbox gains no second consumer.
- Expired, gone and failed deliveries stay queryable, so failure visibility can be built on them.
