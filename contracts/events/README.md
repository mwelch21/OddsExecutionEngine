# Public event contracts

JSON Schemas for the public events that leave the system (ADR-014). Each file is
one versioned type; `examples/` holds one valid event per type.

- Python validates every emitted event against its schema (`backend/tests`).
- Go validates every example and decodes it into the notifier's types
  (`services/notifier/internal/events`).

Adding a field keeps the version. Removing a field or changing its meaning is a
new type (`.v2`), emitted alongside `.v1` for a deprecation window.
