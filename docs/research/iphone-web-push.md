# iPhone Web Push: requirements and HTTPS hosting

Research for [#53](https://github.com/mwelch21/OddsExecutionEngine/issues/53), child of the
notification-layer map [#52](https://github.com/mwelch21/OddsExecutionEngine/issues/52).
Researched 2026-10-03. Sources are listed at the bottom; `[n]` marks each claim's source.
Lines marked **Inference** are reasoning from the sources, not stated by them.

## TL;DR

| Question | Answer |
|---|---|
| iOS minimum | iOS 16.4+, app **added to Home Screen** from Safari, manifest `display: standalone` or `fullscreen` [1][2] |
| Permission | `PushManager.subscribe` called directly inside a tap handler [1][2] |
| App closed? | Works. Service worker is woken per push; it **must** show a notification or Safari revokes the subscription [2][3][7] |
| Server | VAPID (ES256 JWT), aes128gcm payload <= 4 KB, `TTL` required, `Urgency: high` for opportunities, allow `https://*.push.apple.com` [2][4][5] |
| Dead subscriptions | APNs web push returns **410** (`expired`); RFC 8030 says **404**. Treat both as "delete subscription" [2][4] |
| Hosting | **Tailscale Serve** (tailnet-only HTTPS on `*.ts.net`, free) as v1 default. Funnel (public, free, beta) or Cloudflare named tunnel (free, needs a domain ~USD 10/yr) if the phone must not run the Tailscale app [8][9][10][11] |
| Go library | `SherClockHolmes/webpush-go` is usable: MIT, aes128gcm, VAPID, TTL/Urgency/Topic, commits in 2025-2026. Known iOS gotcha: set `Subscriber` to an `https://` URL [12][13] |
| ntfy | Not worth it as a v1 fallback. Only case: a zero-hosting channel for **quota warnings** while the stack is not publicly reachable, via public ntfy.sh topics [14][15] |

## 1. iOS requirements

| Requirement | Detail | Source |
|---|---|---|
| OS version | iOS / iPadOS 16.4 or later. No Apple Developer Program membership needed. | [1][2] |
| Home Screen install | Web Push is only for Home Screen web apps on iOS (Safari tab cannot subscribe). User installs via Share > Add to Home Screen. | [1][2] |
| Manifest | `display` must be `standalone` or `fullscreen`, else it is saved as a bookmark, not a web app. | [1] |
| Service worker | Required to receive `push` events and call `showNotification`. | [1][2] |
| Secure origin | Push API needs a secure context; iPhone cannot reach `localhost`, and `http://<LAN-IP>` is not secure. So the app must be served over real HTTPS. | [6]; **Inference** for the LAN part |
| Permission prompt | Must be triggered by a user gesture: "When the user completes the gesture, call the push subscription method immediately from the gesture's event handler code." | [2] |
| No silent push | "Safari doesn't support invisible push notifications ... If you don't, Safari revokes the push notification permission for your site." | [2][3] |
| Badging | `navigator.setAppBadge` / `clearAppBadge` work in foreground and while handling a push in the background. | [1][2] |
| Focus modes | Notifications integrate with Focus. | [1] |
| Declarative Web Push | iOS 18.4+: payload carries `"web_push": 8030` JSON and the OS shows it without running the service worker. Backward compatible: older devices fall back to the SW handler. Removes the silent-push penalty risk. | [3] |

### App open vs closed

```
Apple push service --> iOS --> wakes service worker --> push event --> showNotification()
                                   (app need not be open)            |
                                                                     +-- skipped? -> subscription revoked
```

- Closed app: delivered. SW is started "as necessary to handle incoming push messages" [7].
- Device offline: APNs stores the message up to `TTL` (max 30 days), limited count, then drops it [2].
- Removing the Home Screen app or changing the origin loses the subscription. **Inference**: permissions and SW registrations are origin-scoped, so the hostname must be stable (this rules out Cloudflare Quick Tunnels, whose hostname changes every run [10]).

## 2. Server side

### Sending a push (Apple's web push endpoint)

| Item | Requirement | Source |
|---|---|---|
| Endpoint | Whatever URL is in the stored subscription (`https://web.push.apple.com/...`). Allow egress to `https://*.push.apple.com`. TLS with SNI; HTTP/1.1 (default) or HTTP/2 via ALPN. | [2] |
| Keys | One VAPID P-256 key pair per server. Public key goes to `PushManager.subscribe({applicationServerKey})`; must match the key in the request (`VapidPkHashMismatch`). | [2][5] |
| JWT | `sub` must be URL or `mailto:`; `aud` = push service origin; `exp` <= 24h ahead. Don't refresh more often than once per hour. | [2] |
| Encryption | `Content-Encoding: aes128gcm` (RFC 8291 / 8188). | [2][4b] |
| Payload size | 4 KB limit (`PayloadTooLarge`, 413). RFC 8291: push services need not accept > 4096 octets, i.e. <= 3993 bytes plaintext. | [2][4b] |
| `TTL` | Required header, positive integer seconds (`BadTtl`). Apple stores up to 30 days. | [2][4] |
| `Urgency` | `very-low`/`low`/`normal`/`high`. Apple: use `high` to attempt immediate delivery. | [2][4] |
| `Topic` | Optional, <= 32 base64url chars; a new message with the same topic replaces an undelivered one. Useful to collapse a burst of opportunities for one watch. | [2][4] |
| Concurrency | HTTP/1.1: max 100 unacknowledged pipelined requests. HTTP/2: respect `SETTINGS_MAX_CONCURRENT_STREAMS`. | [2] |

Suggested defaults for this app (**Inference**):

| Notification | TTL | Urgency | Topic |
|---|---|---|---|
| Opportunity | short (e.g. 300-900 s; a stale price is worse than none) | `high` | per watch intent id |
| Quota warning | long (e.g. 86400 s) | `normal` | `quota` |

### Response handling

| Status | Meaning (Apple) | Action |
|---|---|---|
| 201 | Accepted | record `apns-id` |
| 400 | Bad request (`BadTtl`, `BadUrgency`, `BadWebPushTopic`, `BadWebPushRequest`) | bug, do not retry |
| 403 | Auth error (`BadJwtToken`, `BadVapidPublicKey`, `VapidPkHashMismatch`) | config bug, alert |
| 404 | RFC 8030: subscription expired | delete subscription |
| 410 | "The device token has expired." | delete subscription |
| 413 | Payload > 4 KB | bug, do not retry |
| 429 | Too many requests to same device | back off, retry |
| 500 / 503 | Server error / shutting down | retry with backoff |

Error bodies are JSON with a `reason` key [2]. RFC 8030 uses 404 for expired subscriptions [4]; Apple documents 410 [2]. Handle both the same way. Client side, `pushsubscriptionchange` fires when a subscription is invalidated or about to expire [7]; the SW should re-subscribe and POST the new subscription.

## 3. Hosting: a stable HTTPS origin for the local stack

Key point (**Inference**): Apple push is **outbound** from the notifier, so the public origin only has to serve the PWA (frontend + API calls) to the iPhone. Nothing on the internet needs to call in.

| Option | How | HTTPS / hostname | Cost | Trade-offs |
|---|---|---|---|---|
| **Tailscale Serve** (recommended v1) | `tailscale serve` on the Docker host; Tailscale app on iPhone | Auto cert for `host.tailnet.ts.net`, stable | Free (Personal plan) | Private to tailnet; phone needs Tailscale connected only when **opening** the app, not to receive pushes (**Inference**). Adds tailnet identity headers, a possible stand-in for operator identity before #14 [8][9] |
| Tailscale Funnel | `tailscale funnel 443` | Same `*.ts.net` name, public | Free, all plans incl. Personal | Beta; ports 443/8443/10000 only; non-configurable bandwidth limits; no custom domain; **public with no auth** (#14 not built); on macOS needs the open-source Tailscale client variant [8] |
| Cloudflare Tunnel (named) | `cloudflared` in Compose, public hostname | Your domain, Cloudflare edge cert | Tunnel free; requires a domain added to Cloudflare (~USD 10/yr registration) | Public; can add Cloudflare Access in front. Most "production-like" [10][11] |
| Cloudflare Quick Tunnel | `cloudflared tunnel --url` | Random `*.trycloudflare.com`, **changes every run** | Free, no account | Unusable: hostname change breaks the installed PWA and its subscription; no SSE; 200 in-flight cap; no uptime guarantee [10] |
| Small VPS | Run the Compose stack on e.g. Hetzner CX23 + Caddy/Let's Encrypt | Your domain | ~EUR 5.49/mo (after 2026-06 price rise) + domain | Always on (survives laptop sleep); more ops; moves off "local stack". Price from secondary sources, Hetzner page renders prices client-side [16] |

**Recommendation:** Tailscale Serve for v1. Zero cost, stable `ts.net` origin, valid cert, not exposed to the internet while there is no auth. Funnel is the zero-cost escape hatch if running the Tailscale VPN on the phone is a problem. Move to a VPS only when Auto-Refresh must run while the laptop is asleep, since a sleeping host sends no pushes regardless of tunnel (**Inference**).

## 4. Go Web Push library

`github.com/SherClockHolmes/webpush-go` [12]

| Check | Finding |
|---|---|
| License / health | MIT, ~450 stars, not archived. Releases v1.4.0 (2025-01-02); commits through 2026-04-22 (race fix, VAPID `exp` fix, `AuthScheme` for `vapid` vs `webpush` auth). |
| Spec coverage | aes128gcm encryption, VAPID JWT (golang-jwt/v5), `TTL`, `Urgency`, `Topic`, `RecordSize` (max 4096), `SendNotificationWithContext`. |
| Error handling | Returns the raw `*http.Response`; non-201 is **not** an error. Caller must inspect status (404/410 prune, 429/5xx retry). |
| iOS gotchas | Issue #81 (open): users get `BadJwtToken` / silent failure on iPhone; fixes reported were setting `Subscriber` (empty subject breaks Apple) and using an `https://` URL rather than an email. The lib prefixes `mailto:` to anything not starting `https:` [13]. Also issue #66 open (Edge rejects). |

Verdict: **mature enough** for a single-operator notifier. Small API surface, the protocol is stable, and the remaining risks are config issues covered by an integration test against a real iPhone. Pin `Subscriber` to an `https://` URL and wrap status handling in our own adapter.

## 5. ntfy as a fallback

How ntfy reaches iOS: the iOS app is woken through Firebase/APNs by **ntfy.sh**. A self-hosted server must set `upstream-base-url: "https://ntfy.sh"`, and the phone then fetches the message body from the self-hosted server, which therefore must also be reachable. Without upstream, iOS delivery "can take hours" [14]. Public ntfy.sh topics need no signup (`curl -d "msg" ntfy.sh/topic`), the topic name is effectively a password, and reserved/authenticated topics are a paid "Pro" feature [15].

| Case | ntfy useful? |
|---|---|
| Opportunity notifications | No. Web Push covers it, and ntfy adds a second app, a third-party relay and plaintext-ish topic security. |
| PWA not installed / Web Push subscription lost | Marginal. Fix the subscription instead. |
| Quota warnings while the stack has no public origin, or as an ops "notifier is broken" alarm | **Yes**, this is the one case: a public ntfy.sh topic needs no hosting, so it still works if the HTTPS origin or Web Push path is down. |

Verdict: **do not build ntfy in v1.** Keep it as a documented option for an out-of-band ops alarm. The channel-agnostic delivery core in #52 means it can be added later as one more channel adapter.

## Sources

1. WebKit blog, "Web Push for Web Apps on iOS and iPadOS" (2023). https://webkit.org/blog/13878/web-push-for-web-apps-on-ios-and-ipados/
2. Apple Developer, "Sending web push notifications in web apps and browsers". https://developer.apple.com/documentation/usernotifications/sending-web-push-notifications-in-web-apps-and-browsers (read via the doc JSON at `developer.apple.com/tutorials/data/documentation/usernotifications/sending-web-push-notifications-in-web-apps-and-browsers.json`)
3. WebKit blog, "Meet Declarative Web Push". https://webkit.org/blog/16535/meet-declarative-web-push/
4. RFC 8030, Generic Event Delivery Using HTTP Push (sections 5.2 TTL, 5.3 Urgency, 5.4 Topic, 7.3 expiry 404). https://www.rfc-editor.org/rfc/rfc8030.html
   4b. RFC 8291, Message Encryption for Web Push (section 4, 4096-octet limit, aes128gcm). https://www.rfc-editor.org/rfc/rfc8291.html
5. RFC 8292, VAPID for Web Push. https://www.rfc-editor.org/rfc/rfc8292.html
6. MDN, PushManager / secure contexts. https://developer.mozilla.org/en-US/docs/Web/API/PushManager
7. MDN, Push API. https://developer.mozilla.org/en-US/docs/Web/API/Push_API
8. Tailscale KB, Funnel. https://tailscale.com/kb/1223/funnel ; pricing table lists Funnel on Personal: https://tailscale.com/pricing
9. Tailscale KB, Serve. https://tailscale.com/kb/1312/serve
10. Cloudflare docs, Quick Tunnels. https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/do-more-with-tunnels/trycloudflare/
11. Cloudflare docs, Create a remotely-managed tunnel ("you must add a website to Cloudflare"). https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/get-started/create-remote-tunnel/ ; free tunnels: https://blog.cloudflare.com/tunnel-for-everyone/
12. webpush-go repository. https://github.com/SherClockHolmes/webpush-go (source: `webpush.go`, `vapid.go`, `go.mod`; release and commit data via GitHub API)
13. webpush-go issue #81, Apple devices cannot receive. https://github.com/SherClockHolmes/webpush-go/issues/81 ; issue #61 (403 on iOS). https://github.com/SherClockHolmes/webpush-go/issues/61
14. ntfy docs, config: iOS instant notifications and `upstream-base-url`. https://docs.ntfy.sh/config/
15. ntfy docs, publishing. https://docs.ntfy.sh/publish/
16. Hetzner Cloud. https://www.hetzner.com/cloud/ (prices render client-side; figures from https://northflank.com/blog/hetzner-cloud-server-price-increases and https://www.cloudhim.com/cloud-costs/hetzner-cx22-pricing-2026, secondary)
