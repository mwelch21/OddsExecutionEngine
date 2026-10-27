---
scope: feature
target: web-push
synced_at: cb3f280
sources:
  - backend/app/application/watch_intent_service.py
  - backend/app/application/destination_service.py
  - backend/app/api/destination_router.py
  - backend/app/domain/public_events.py
  - backend/app/infrastructure/persistence/destination_uow.py
  - backend/db/migrations/versions/20261018_0009_public_events_outbox.py
  - backend/db/migrations/versions/20261018_0011_deliveries.py
  - contracts/events/oddsengine.opportunity.identified.v1.json
  - frontend/src/lib/push.ts
  - frontend/src/components/PushToggle.tsx
  - frontend/public/sw.js
  - frontend/public/manifest.webmanifest
  - frontend/vite.config.ts
  - services/notifier/internal/notifier/notifier.go
  - services/notifier/internal/store/store.go
  - services/notifier/internal/events/events.go
  - services/notifier/internal/push/push.go
  - services/notifier/internal/push/payload.go
  - services/notifier/internal/config/config.go
  - docker-compose.yml
links: []
---

# Web Push
> Register desktop and iPhone browsers, then deliver a test notification through the public outbox.

<!-- ff:high-level -->
## High level
> Two producers write the public outbox; the Go notifier fans out, renders and sends.

```mermaid
flowchart LR
  PushToggle --> DestinationService
  WatchIntentService -->|opportunity.identified.v1| public_events
  DestinationService -->|destination.test.v1| public_events
  public_events -->|NOTIFY or sweep| Notifier
  Notifier --> deliveries
  Notifier -->|Render| events
  Notifier -->|VAPID| WebPushSender
  WebPushSender --> PushService
  PushService --> sw.js
```
<!-- /ff -->

<!-- ff:data-flow -->
## Data flow
> Opportunity path. The test path is the same from public_events on, aimed at one destination.

```mermaid
sequenceDiagram
  participant Browser
  participant WatchIntentService
  participant Postgres
  participant Notifier
  participant PushService
  Browser->>WatchIntentService: POST watch-intents fillable
  WatchIntentService->>Postgres: Commit opportunity and public event with expires_at
  Postgres-->>Notifier: NOTIFY or 30s sweep
  Notifier->>Postgres: Fan out one delivery per active destination
  Notifier->>Postgres: Commit fenced claim
  Notifier->>PushService: Apple gets declarative push, others plain JSON
  PushService-->>Browser: Notification with APP_ORIGIN link
  Notifier->>Postgres: Record delivered, failed or expired
```
<!-- /ff -->

<!-- ff:state -->
## Delivery state
> A claim changes lease/token fields while status stays pending. Delivered means push-service acceptance.

```mermaid
stateDiagram-v2
  [*] --> pending: fan out
  pending --> pending: claim or expired lease recovery
  pending --> delivered: push service 2xx
  pending --> failed: render or send error
  pending --> expired: now past the event's expiry
```
<!-- /ff -->

<!-- ff:decisions -->
## Routing and guards
> Fan-out, expiry and payload shape are per event type and endpoint; the API guards test requests.

```mermaid
flowchart TD
  FanOut{FanOut} -->|destination.test.v1| subject_destination
  FanOut -->|opportunity.identified.v1| every_active_destination
  Expiry{ExpiresAt} -->|test| plus_10_minutes
  Expiry -->|opportunity| data_expires_at
  Expiry -->|expires_at missing| already_expired
  Payload{Payload} -->|push.apple.com| declarative_8030
  Payload -->|other endpoint| plain_notification
  DestinationService{DestinationService} -->|missing destination| HTTP404
  DestinationService -->|disabled destination| HTTP409
  DestinationService -->|within 10 seconds| HTTP429
```
<!-- /ff -->

<!-- ff:dependencies -->
## Device access and dependencies
> Tailscale Serve provides private HTTPS access to the app. PushService delivers notifications separately.

```mermaid
flowchart LR
  Desktop -->|localhost| Vite
  iPhone -->|tailnet HTTPS| TailscaleServe
  TailscaleServe --> Vite
  Vite -->|proxy| API
  API --> Postgres
  Notifier --> Postgres
  Notifier -->|APP_ORIGIN links| PushService
```

| Dependency | Current behavior |
|---|---|
| Desktop access | Open `http://localhost:5173` or the `ts.net` URL; enable notifications in that browser. Each origin is its own subscription, so using both means two notifications per opportunity. |
| iPhone access | Same tailnet as Mac; MagicDNS and HTTPS certificates enabled; `tailscale serve --bg 5173`. Open printed HTTPS URL in Safari, Share → Add to Home Screen, launch OddsCafe, enable notifications. |
| `APP_ORIGIN` | Notifier only, required. Absolute origin that notification links open, e.g. `https://<mac>.<tailnet>.ts.net`. Compose defaults to `http://localhost:$FRONTEND_PORT`. |
| Browser permission | User tap grants permission; service worker registers and subscription is stored through `POST /destinations/web-push`. |
| VAPID | Existing keys stay stable. API gets public key; only notifier gets private key. Sender strips configured `mailto:` prefix before webpush-go adds it. |
| Persistence | `destinations` stores endpoint and encryption keys; public responses omit keys. `public_events` stores CloudEvents. Unique event/destination pair prevents duplicate delivery rows. |
| Expiry | Test: 10 minutes. Opportunity: `data.expires_at` = created_at + opportunity TTL (720 min default). Events without `expires_at` expire unsent. |
| Payload | Apple endpoints: Declarative Web Push (`web_push: 8030`, `navigate`), opened by iOS 18.4+ without the service worker. Others: `{title, body, url, tag}`, shown by `sw.js`. Max 3993 bytes. |
| Display | Opportunity: title `Away @ Home`, body `Selection price @ book · target price · fillable`, tap opens `/?event=<id>&opportunity=<id>`. The app does not read those params yet (#71). |
| Worker | 30-second sweep, 60-second lease, fresh claim token; stale results cannot overwrite a newer claim. `dispatched_at` means fan-out completed. |
| Runtime | Mac must remain awake and online, with app and notifier running. After a branch switch, rebuild the notifier image (`just refresh` once #84 lands). |
| Current scope | Test and opportunity notifications are delivered. Retries/backoff and dead-subscription handling are #73. |
| Manual validation | 2026-10-26: opportunity notification delivered to Mac and iPhone; iPhone cold-launch tap opened the Home Screen app (#72). |
| Operator commands | See [Web Push runbook](../../runbooks/web-push.md). Run repo commands from repository root. |
<!-- /ff -->

## Notes

