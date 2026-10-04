# ADR-006: Persist workflow events and publish only after commit

- Status: accepted
- Date: 2026-04-12

## Context

Stage 3 introduces the first explicit event boundary around recommendation generation. The system needs an audit trail of emitted workflow events and must avoid publishing events for transactions that later roll back.

## Decision

Persist workflow events in the `workflow_events` table within the same transaction as recommendation writes, and publish them only after a successful commit.

## Why

- preserves an append-only workflow audit trail
- keeps event visibility aligned with committed database state
- creates a simple outbox-style boundary without introducing a full event bus yet

## Rejected alternatives

- publish before commit: risks leaking rolled-back events
- publish without persistence: loses durable workflow history
- persist without publishing: delays stage 3 integration boundary value

## Consequences

- recommendation workflows must stage events during the unit of work
- rollback paths must clear staged events and publish nothing
- initial publishers remain synchronous and process-local
