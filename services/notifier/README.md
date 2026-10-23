# notifier

Go delivery worker (ADR-013). Reads the Postgres public outbox, fans each
public event out into deliveries, and sends them over Web Push (ADR-014,
ADR-015). It has no HTTP API, and Alembic owns every table it touches.

```
public_events --NOTIFY / 30s sweep--> fan-out --> deliveries --claim--> Web Push
```

| Package | Job |
|---|---|
| `internal/config` | Environment: `DATABASE_URL`, `VAPID_PUBLIC_KEY`, `VAPID_PRIVATE_KEY`, `VAPID_SUBJECT`, `APP_ORIGIN` |
| `internal/events` | Public event types, expiry per event, rendering to a notification |
| `internal/store` | Fan-out, `SKIP LOCKED` claims with lease + claim token, fenced results |
| `internal/push` | VAPID-signed Web Push via `webpush-go`; Declarative Web Push for Apple endpoints |
| `internal/notifier` | The loop: work, then wait for NOTIFY or the sweep |

Delivered today:

| Type | Goes to | Expires | Tap opens |
|---|---|---|---|
| `destination.test.v1` | the one destination in `subject` | 10 min after the request | `/` |
| `opportunity.identified.v1` | every active destination | `data.expires_at` (the opportunity TTL) | `/?event=<id>&opportunity=<id>` |

Links are absolute under `APP_ORIGIN`, the PWA's origin (your `*.ts.net` URL on
a phone). Apple endpoints get Declarative Web Push (`"web_push": 8030`), so iOS
18.4+ opens the link itself without the service worker.

Retries, `gone` and lease recovery tests arrive with "Delivery resilience" (#73).

## Run

`docker compose up -d notifier` (it is the only service that receives
`VAPID_PRIVATE_KEY`). See `docs/runbooks/web-push.md`.

## Test

```bash
just test-notifier   # migrates the test DB with Alembic, then go test
```

Integration tests skip unless `NOTIFIER_TEST_DATABASE_URL` is set.
