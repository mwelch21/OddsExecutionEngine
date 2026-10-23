# ADR-001: Keep migrations in the backend repo

- Status: accepted
- Date: 2026-04-11

## Context

Stage 2 introduced persistent storage and schema ownership. The backend is still the only service that owns this schema.

## Decision

Keep migration files in this repository under `backend/db/migrations` instead of creating a separate database project.

## Why

- app code, repositories, tests, and schema changes evolve together
- one PR can change behavior and schema consistently
- agentic implementation and review stay schema-aware without cross-repo coordination

## Rejected alternatives

- separate DB repo now: adds overhead before multiple services own the schema

## Consequences

- schema changes must land with migration files in this repo
- future split is allowed if schema ownership broadens
