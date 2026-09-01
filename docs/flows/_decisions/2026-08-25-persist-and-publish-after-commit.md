---
type: decision
project: odds-execution-engine
title: Persist and publish after commit
tags:
  - decision
  - domain/events
updated: 2026-08-25
---

# Persist and publish after commit

Date: 2026-08-25
Context: Both [[quote-ingestion-refresh]] and [[execution-recommendation]] flows
Services: QuoteIngestionService, RecommendationService, SqlAlchemyQuoteIngestionUnitOfWork, SqlAlchemyRecommendationUnitOfWork

## Context

Both workflows emit domain events (QuotesRefreshed, QuoteUpdated, MarketSnapshotCreated, OrderIntentSubmitted, ExecutionRecommendationGenerated). The system needs an audit trail and must avoid publishing events for transactions that roll back.

## Options considered

1. Publish before commit — fire events immediately during the workflow
2. Publish without persistence — emit but don't store events
3. Persist in same transaction, publish after commit — outbox-style pattern

## Decision

Option 3: Persist in same transaction, publish after commit.

## Why

Events are persisted in the `workflow_events` table within the same DB transaction as the business data. Publishing happens only after `session.commit()` succeeds. This guarantees the event audit trail matches committed state and prevents leaking rolled-back events to downstream consumers. The tradeoff is that if publishing fails after commit, the event is persisted but not delivered — acceptable at this stage since the publisher is synchronous/logging-only.

## Consequences

- All UoW implementations must call `stage_event()` during the transaction and `_persist_staged_events()` before commit
- Rollback paths clear staged events and publish nothing
- `committed_events` property is only populated after successful `__exit__`
- Future async publishers must handle the "persisted but not yet published" gap (outbox polling or retry)
