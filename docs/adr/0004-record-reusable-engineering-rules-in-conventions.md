# ADR-004: Record reusable engineering rules in conventions

- Status: accepted
- Date: 2026-04-11

## Context

Architecture and workflow expectations were scattered across code, tests, and chat history.

## Decision

Store major one-time choices as ADRs (now one file each under `docs/adr/`, indexed by `docs/architecture/decisions.md`) and general standing rules in `docs/architecture/conventions.md`.

## Why

- gives agents and humans one place to check
- reduces repeated drift in architecture choices
- makes rationale visible instead of implicit

## Rejected alternatives

- keep all rules only in `agents.md`: too mixed between process and architecture

## Consequences

- agents must read and update these docs when making material architecture changes
