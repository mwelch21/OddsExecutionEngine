# ADR-002: No runtime schema creation in app startup

- Status: accepted
- Date: 2026-04-11

## Context

`metadata.create_all()` in app startup creates hidden schema mutation and makes production state depend on boot order.

## Decision

All schema creation and evolution must happen through explicit migrations. App startup must not mutate schema.

## Why

- predictable deploys
- visible schema history
- safer production operations
- tests can prove the migration path directly

## Rejected alternatives

- keep `create_all()` for convenience: too implicit and unsafe for long-term use

## Consequences

- local/dev setup requires a migration step
- deploy workflows must run migrations before app traffic
