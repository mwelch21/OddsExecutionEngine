# ADR-007: Stage 4 uses minimal canonical quote normalization

- Status: accepted
- Date: 2026-04-12

## Context

Stage 4 introduces the first quote ingestion workflow. The repo already has a canonical `Quote` model and market identity rules, but no separate raw-provider schema layer yet.

## Decision

Use a minimal normalization step that filters provider data directly into canonical `Quote` values and persists them through the existing market identity and latest/history quote tables.

## Why

- keeps stage 4 focused on the ingestion workflow instead of expanding provider modeling prematurely
- reuses the deterministic `Quote` shape already consumed by recommendation logic
- keeps the mock-provider implementation simple and testable

## Rejected alternatives

- introduce richer raw-provider models now: extra scope before multiple providers exist
- persist provider payloads directly without normalization: weakens deterministic ingestion boundaries

## Consequences

- stage 4 providers must produce data that can normalize into canonical `Quote` values
- richer provider metadata can be added later without replacing the first ingestion boundary
