# ADR-013: Notification delivery is a Go service reading the Postgres outbox

- Status: accepted
- Date: 2026-10-03

## Context

Opportunity notifications and quota warnings must reach the operator's iPhone as Web Push. Today `OpportunityIdentified` is published after commit to a logging publisher and goes nowhere. Delivery means calling Apple's push service: an external system with its own latency and failure modes, and retries that outlive any one request.

The standing anti-goal was "no premature microservices". That phrase reads as "never", which is not what it means. This ADR turns it into a stated rule and applies it to delivery.

## Decision

Notification delivery runs as a separate **notifier** service, written in **Go**, in this repo under `services/notifier/`.

- **Scope.** The notifier is an internal delivery worker. It reads the outbox, renders the public event, sends Web Push, and records the outcome. It exposes no public API beyond a health check. The Python API stays the single public API surface (API parity).
- **Transport.** The notifier reads the public outbox from the shared Postgres (amended by ADR-014; it never reads `workflow_events`). `LISTEN/NOTIFY` wakes it rather than a polling timer. Read, claim and acknowledge semantics are decided separately (the outbox-consumption ticket).
- **Schema.** Alembic remains the only schema owner, including tables only the notifier uses. The Go service never migrates.
- **Contract.** The public event schema is pinned by a contract test both languages run, so the Python producer and the Go consumer cannot drift.
- **Runtime.** It is a `notifier` service in compose (started by `just up`), configured from the shared `.env` (database URL, VAPID keys). CI runs `go vet`, `golangci-lint` and `go test` against migrated Postgres.

### Extraction rule

A component becomes its own service only when at least two of these hold, and an ADR makes the case:

1. Its runtime profile differs (long-running or concurrent vs request/response)
2. Its failures must not take the API down, or the API's failures must not take it down
3. It talks to an external system with different reliability or latency
4. It needs its own deploy or scaling cadence

The notifier meets 1, 2 and 3.

## Why Go

At this volume a Python worker would do the job for less. Go is a deliberate investment, not a performance need: it establishes the polyglot service boundary (contract test, shared outbox, single schema owner) that the planned Go ingestion service will follow, and a concurrent dispatcher with retries is a natural fit for it. The Web Push library `webpush-go` is mature enough (see the iPhone Web Push research).

## Rejected alternatives

- **Publisher adapter inside the API process:** puts Apple's latency and failures on the request path, and loses delivery if the process dies after commit.
- **Python worker in the same codebase:** cheaper, reuses the Pydantic event models. Rejected for the investment reason above, not on merit at current volume.
- **HTTP call from the API to the notifier after commit:** loses events while the notifier is down. The outbox already holds them durably.
- **A broker (Redis streams, NATS) now:** new infrastructure before a second consumer needs it. It stays the next extraction step.
- **A separate repo:** cross-repo lockstep for one developer, and it would split schema ownership. `git subtree split` keeps that option cheap later.

## Consequences

- The repo becomes polyglot: a second toolchain in CI, compose and local dev.
- The public event schema is now a cross-language contract, with a test guarding it.
- Delivery survives API restarts and notifier downtime, because events wait in the outbox.
- Any future extraction is judged against the rule above.
