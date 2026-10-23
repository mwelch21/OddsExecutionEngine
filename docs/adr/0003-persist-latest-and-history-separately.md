# ADR-003: Persist latest and history separately

- Status: accepted
- Date: 2026-04-11

## Context

Recommendation paths want fast latest-state reads, while audit and future analytics want quote history.

## Decision

Use `market_quotes_latest` for current execution reads and `market_quotes_history` for append-style historical storage.

## Why

- simple query path for recommendation
- preserves audit trail
- matches product requirement for latest vs history split

## Rejected alternatives

- history-only queries for everything: slower and noisier read path
- latest-only storage: loses auditability

## Consequences

- quote ingestion must maintain both tables consistently
