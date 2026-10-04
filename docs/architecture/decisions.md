# Architecture Decisions

ADRs live one per file in [`docs/adr/`](../adr/), numbered `NNNN-slug.md`. Add a new decision there as the next number; this page is only an index.

- [ADR-001: Keep migrations in the backend repo](../adr/0001-keep-migrations-in-the-backend-repo.md)
- [ADR-002: No runtime schema creation in app startup](../adr/0002-no-runtime-schema-creation-in-app-startup.md)
- [ADR-003: Persist latest and history separately](../adr/0003-persist-latest-and-history-separately.md)
- [ADR-004: Record reusable engineering rules in conventions](../adr/0004-record-reusable-engineering-rules-in-conventions.md)
- [ADR-005: Stage 2 enhanced is the operational baseline before event work](../adr/0005-stage-2-enhanced-is-the-operational-baseline-before-event-wo.md)
- [ADR-006: Persist workflow events and publish only after commit](../adr/0006-persist-workflow-events-and-publish-only-after-commit.md)
- [ADR-007: Stage 4 uses minimal canonical quote normalization](../adr/0007-stage-4-uses-minimal-canonical-quote-normalization.md)
- [ADR-008: One opportunity per watch, and the watch is terminal once it fires](../adr/0008-one-opportunity-per-watch-and-the-watch-is-terminal-once-it.md)
- [ADR-009: Store the book's quote time and the ingest time as separate columns](../adr/0009-store-the-book-s-quote-time-and-the-ingest-time-as-separate.md)
- [ADR-010: Event browse reads go through a read-only unit of work](../adr/0010-event-browse-reads-go-through-a-read-only-unit-of-work.md)
- [ADR-011: A deliberate refresh always pulls live; the cache only collapses simultaneity](../adr/0011-a-deliberate-refresh-always-pulls-live-the-cache-only-collap.md)
- [ADR-012: Per-event refresh is one single-event call, its sport resolved from what we already store](../adr/0012-per-event-refresh-is-one-single-event-call-its-sport-resolve.md)
- [ADR-013: Notification delivery is a Go service reading the Postgres outbox](../adr/0013-notification-delivery-is-a-go-service-reading-the-postgres-outbox.md)
- [ADR-014: Public events are versioned CloudEvents in their own outbox](../adr/0014-public-events-are-versioned-cloudevents-in-their-own-outbox.md)
