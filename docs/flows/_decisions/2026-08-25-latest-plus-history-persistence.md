---
type: decision
project: odds-execution-engine
title: Latest plus history persistence
tags:
  - decision
  - domain/quotes
  - persistence
updated: 2026-08-25
---

# Latest plus history persistence

Date: 2026-08-25
Context: [[quote-ingestion-refresh]] flow
Services: SqlAlchemyQuoteIngestionUnitOfWork

## Context

The recommendation flow needs fast reads of current quote state, while audit and analytics require historical quote data. A single table serving both purposes creates either slow reads or lost history.

## Options considered

1. Single table with "is_latest" flag — query latest via filter
2. History-only with materialized view — maintain a view for current state
3. Separate `market_quotes_latest` and `market_quotes_history` tables — dual-write on ingestion

## Decision

Option 3: Separate latest and history tables.

## Why

`market_quotes_latest` is keyed by (market_id, sportsbook) for O(1) upsert and simple JOIN for recommendation reads. `market_quotes_history` is append-only for audit. The dual-write cost is minimal (one DELETE+INSERT for latest, one INSERT for history per quote) and avoids complex queries or view maintenance. The recommendation hot path reads only `market_quotes_latest` without filtering noise from historical rows.

## Consequences

- Quote ingestion must maintain both tables in the same transaction
- Latest table uses DELETE+INSERT (not UPSERT) for simplicity — if Postgres dialect support for ON CONFLICT is added later, this could be optimized
- History table grows unbounded — will eventually need retention/archival policy
- Any aggregation or time-series analysis queries go against history, not latest
