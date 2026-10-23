# notifier

Go delivery worker (ADR-013). Reads the Postgres public outbox, fans each
public event out into deliveries, and sends them over Web Push (ADR-014,
ADR-015). It has no HTTP API, and Alembic owns every table it touches.

```
public_events --NOTIFY / 30s sweep--> fan-out --> deliveries --claim--> Web Push
```

| Package | Job |
|---|---|
| `internal/config` | Environment: `DATABASE_URL`, `VAPID_PUBLIC_KEY`, `VAPID_PRIVATE_KEY`, `VAPID_SUBJECT` |
| `internal/events` | Public event types, max age per type, rendering to a notification |
| `internal/store` | Fan-out, `SKIP LOCKED` claims with lease + claim token, fenced results |
| `internal/push` | VAPID-signed Web Push via `webpush-go` |
| `internal/notifier` | The loop: work, then wait for NOTIFY or the sweep |

Delivered today: `destination.test.v1`. Opportunity notifications arrive with
"Opportunity notifications reach the operator" (#72); retries, `gone` and lease
recovery tests with "Delivery resilience" (#73).

## Run

`docker compose up -d notifier` (it is the only service that receives
`VAPID_PRIVATE_KEY`). See `docs/runbooks/web-push.md`.

## Test

```bash
just test-notifier   # migrates the test DB with Alembic, then go test
```

Integration tests skip unless `NOTIFIER_TEST_DATABASE_URL` is set.
