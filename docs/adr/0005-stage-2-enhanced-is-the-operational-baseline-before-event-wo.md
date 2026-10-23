# ADR-005: Stage 2 enhanced is the operational baseline before event work

- Status: accepted
- Date: 2026-04-11

## Context

Stage 2 introduced explicit migrations, persistence adapters, and seed tooling. Stage 3 should not mix event-layer design with unfinished persistence workflow cleanup.

## Decision

Treat stage 2 enhanced as the required operational baseline. Before event-layer work, the repo must have explicit migration commands, explicit demo seed commands, and clear Postgres-first persistence test policy.

## Why

- keeps event work focused on event boundaries instead of DB workflow cleanup
- makes local and CI setup repeatable
- prevents SQLite convenience coverage from being mistaken for persistence truth

## Rejected alternatives

- start stage 3 while persistence ergonomics are still transitional

## Consequences

- Postgres remains the required integration truth path
- SQLite is limited to smoke or convenience coverage
- stage 3 begins only after migration and seed workflows are explicit
