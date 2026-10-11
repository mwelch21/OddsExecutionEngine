# Deep links: making a tapped notification open the right screen

Research for [#66](https://github.com/mwelch21/OddsExecutionEngine/issues/66), child of the
notification-layer map [#52](https://github.com/mwelch21/OddsExecutionEngine/issues/52).
Researched 2026-10-11. Sources are listed at the bottom; `[n]` marks each claim's source.
Lines marked **Inference** are reasoning from the sources, not stated by them. Lines marked
**Second-hand** come from bug-tracker reports by non-vendor developers, not from a vendor
statement or spec.

## TL;DR

| Question | Answer |
|---|---|
| Recommended URL | `https://<host>.<tailnet>.ts.net/?event=<eventId>&opportunity=<opportunityId>`: query string on the app root, absolute, same origin, inside manifest `scope: "/"` |
| Why not `/events/{id}` | `/events` is already an **API** prefix. The Vite proxy (and any Serve mount per API prefix) sends `/events/...` to FastAPI, so the SPA would never see it. A root query string also needs no server-side SPA fallback |
| iPhone tap | Opens the **Home Screen web app**, not Safari [8]. On iOS 18.4+ a Declarative Web Push message is shown and navigated **by the OS**, with no service worker involved [3][5] |
| iPhone SW click handler | Works, but has a long tail of WebKit bugs around a cold-launched app (`notificationclick` not firing, `openWindow`/`navigate` racing the page load). One is still open [9][10][11] |
| Desktop Chrome | Ignores `navigate`, so the service worker's `notificationclick` handler does the work: focus a matching window and navigate it, else `openWindow` [1][2][6] |
| Desktop Safari | Safari 18.4+ handles a declarative message itself (navigate on click). Older: same SW path as Chrome [3][6] |
| Scope / origin | `openWindow` and `navigate` return `null` for a cross-origin URL [1][2]. Keep the URL same-origin and inside the manifest `scope`; out-of-scope behaviour is implementation-defined [7] |
| Tailscale Serve | No path constraint beyond: a stable `*.ts.net` hostname (the origin), HTTPS. Serve picks the longest mount prefix and **strips it** before proxying; it has no SPA fallback for file serving [12] |
| SPA change | No router. Read `location.search` once on load into the existing `selectedEventId` state plus a new `pinnedOpportunityId`; write it back with `history.pushState` on select / back; listen to `popstate`. About 30 lines in `App.tsx` |

## 1. How a tap is dispatched (spec model)

```
                    user taps notification
                              |
            notification has a navigation URL (`navigate`)?
                 |                                   |
                yes                                  no
                 |                                   |
   UA navigates an existing top-level        persistent (SW) notification?
   context OR creates a new one                      |
   (implementation-defined).                        yes
   notificationclick is NOT fired.                   |
                                       fire `notificationclick` in the SW
                                       -> clients.matchAll / focus / navigate / openWindow
```

Source: Notifications Standard, "Activating a notification": *"If navigationURL is non-null: Select one of the following two options in an implementation-defined manner: Navigate an existing top-level traversable ... Create a fresh top-level traversable given navigationURL. ... Return."* Only if it is null does the UA *"Fire a service worker notification event named "notificationclick""* [5].

Where the `navigate` member comes from:

| Path | Who builds the notification | Has `navigate`? | Click handled by |
|---|---|---|---|
| Declarative Web Push message (`"web_push": 8030`), not `mutable` | The browser/OS, no JS. Push event **not** fired [4] | Yes, required [3][4] | UA navigation |
| Declarative message with `"mutable": true` | SW `push` event may replace it; fallback is the declarative one [3][4] | Whatever the SW passes | Depends |
| Classic push, SW calls `showNotification(title, {data})` | SW | No | SW `notificationclick` |

The declarative `navigate` URL is parsed against the push subscription's scope [4], so a relative URL works, but an absolute one is unambiguous. Neither spec adds a same-origin rule for `navigate` [4][5].

Support for `navigate` (MDN browser-compat-data [6]):

| API | Chrome | Safari (macOS) | Safari iOS | Firefox |
|---|---|---|---|---|
| `Notification.navigate` | no | 18.4 | 18.4 | 158 |
| `PushEvent.notification` (declarative) | no | 18.4 | 18.4 | no |
| `notificationclick` | 40 | 16 (macOS 13+) | listed "no" (see 2.3) | 44 |
| `Clients.openWindow` | 40 | 11.1 | 11.1 | 44 |
| `Clients.matchAll` | 42 | 11.1 | 11.1 | 54 |
| `WindowClient.focus` | 42 | 11.1 | 11.1 | 44 |
| `WindowClient.navigate` | 49 | 16 (threw `NotSupportedError` before) | 16 | 50 |

## 2. iPhone (Home Screen web app, iOS 16.4+)

### 2.1 Web app or Safari?

- Web Push on iOS exists only for Home Screen web apps [8]. WebKit's own bug title describes the tap path as "a Home Screen web app **launched to handle notificationclick**" [9]: the tap launches the web app, not a Safari tab.
- Since Safari 26, every site added to the Home Screen opens as a web app by default, manifest optional [13]. The app still needs `display: standalone` for push on older iOS (see the #53 research).
- **Unverified first-party:** whether a declarative `navigate` URL opens inside the web app or in Safari is not stated by Apple or WebKit. **Inference:** the subscription belongs to the web app, so the OS should route to it. Must be checked on the device.

### 2.2 Which path runs

| iOS version | Message format | What happens on tap |
|---|---|---|
| 16.4 - 18.3 | any JSON | SW `push` -> `showNotification` -> SW `notificationclick` |
| 18.4+ | declarative, not mutable | OS shows it, OS navigates to `navigate` on tap. SW not involved [3][4] |
| 18.4+ | declarative, `mutable: true` | SW may replace it; if the replacement has no `navigate`, back to `notificationclick` |

**Inference:** the operator's iPhone in late 2026 runs iOS 18.4+ (likely 26), so the declarative path is the one that will run there. Sending declarative JSON without `mutable` routes the iPhone around every SW click bug below.

### 2.3 Known WebKit bugs on the SW click path

| Bug | What | Status |
|---|---|---|
| 252544 [9] | Window client launched for `notificationclick` is "inert for a short period": `postMessage`, `focus()`, `navigate()` fail until the document's network response arrives (Brady Eidson, Apple) | Fixed April 2023 (`262711@main`), for `postMessage` |
| 268797 [10] | `notificationclick` does not fire in a Home Screen app on cold launch. Apple's youenn fablet: "iOS 17.5 received some fixes in that area." Reporters say it persists into iOS 18.7 | **Open**. Reports are **second-hand**. Workarounds in comments: `setTimeout` delay, or move to Declarative Web Push |
| 279456 [11] | `Clients.openWindow` resolves before the window is ready | **Open** |
| 279458 [11b] | `matchAll` resolves too early | Fixed Oct 2024 (`285953@main`) |
| 259212 [14] | `openWindow('/x')` opened the app at its home page | Closed "configuration changed": reporter found it **only failed on localhost**, worked over HTTPS. **Second-hand** |

MDN's compat data lists `notificationclick` as unsupported on Safari iOS [6]. That conflicts with WebKit's own tracker, where Apple engineers fix `notificationclick` bugs in Home Screen apps [9][10]. **Inference:** the compat entry is stale. Do not rely on it.

### 2.4 Scope and start_url

- `start_url` must be within `scope`, or the `scope` member is ignored [7]. Default scope is the start URL's directory [7].
- *"Navigating the web application "out of scope" will cause the manifest to no longer be applied ... It's left up to implementers"* [7]. Apple does not document what iOS shows for an out-of-scope tap. **Inference:** keep every notification URL inside `scope` and avoid finding out.
- `openWindow` / `navigate` to another origin resolve to `null` [1][2]: no window client to work with.
- Recommendation: manifest `"scope": "/"`, `"start_url": "/"`, SW registered at `/sw.js` (scope `/`). Every `/?...` URL is then in scope and controlled.

## 3. Desktop Chrome and Safari

| Case | Chrome (any version today) | Safari 18.4+ (macOS) | Safari 16 - 18.3 |
|---|---|---|---|
| Who handles the click | SW `notificationclick` (`navigate` unsupported [6]) | UA, via declarative `navigate` [3][6] | SW `notificationclick` |
| App tab already open | `matchAll({type:"window"})` finds it, most recently focused first [2b][6]; `focus()` then `navigate(url)` | Implementation-defined: reuse a tab or open a new one [5] | Same as Chrome |
| No tab open | `openWindow(url)` opens a tab; may open inside an installed web-app window (Android since Chrome 51, recently Windows) [1][6] | New tab | `openWindow` |
| Activation rule | `focus()` and `openWindow()` reject with `InvalidAccessError` unless a window in the origin has transient activation [2][2b]. A notification click provides it (Firefox: only then [1]) | n/a | same |

- Chrome's guidance: compare absolute URLs (`new URL(path, self.location.origin).href`) and use `includeUncontrolled: true` [15].
- `WindowClient.navigate()` rejects with `TypeError` if the client is not controlled by this service worker [2b]. **Inference:** call `clients.claim()` in the SW `activate` handler so open tabs are controlled, and fall back to `openWindow` if `navigate` throws.
- **Second-hand, not verified here:** desktop Chrome receives pushes only while the browser process is running. The #53 research already notes a sleeping host sends nothing.

## 4. Tailscale Serve (`*.ts.net`)

From the Serve source (`ipn/ipnlocal/serve.go`) [12] and KB [16][17]:

| Fact | Consequence |
|---|---|
| The origin is `https://<device>.<tailnet>.ts.net` (HTTPS certs must be enabled) [16] | It is the PWA's identity. Renaming the device changes the origin and orphans the installed app and its subscription (**Inference**, as in #53) |
| Handler lookup: exact path, else walk up parent directories: longest mount prefix wins [12] | One origin can host the SPA at `/` and the API on another mount |
| `// Trim the mount point from the URL path before proxying.` (`http.StripPrefix`) [12] | Mounting FastAPI at `/api` would strip `/api`, so the backend needs no change. Not needed for v1 |
| File/dir serving has no SPA fallback [12] | A path URL like `/board/<id>` would 404 under a static mount. A root query string never needs fallback |
| Serve adds `Tailscale-User-Login` and friends [16]; tailnet-only [16] | No effect on deep links |

No other path or origin constraint was found.

## 5. The SPA side

Current state (`frontend/src` on `development`): no router. `App.tsx` holds `selectedEventId` in state and switches between `EventList` and `LineBoard` via `handleSelectEvent` / `handleBack`. `api.ts` calls `/events`, `/sports`, `/watch-intents`, `/opportunities`, `/execution`, `/ingestion` at the origin root, and `vite.config.ts` proxies those prefixes to FastAPI.

That is why `/events/{id}?opportunity={id}` (the ticket's example) does not work: it is an API path in this app. Options:

| Option | URL | Server work | Client work | Verdict |
|---|---|---|---|---|
| **A. Query on root** | `/?event=<e>&opportunity=<o>` | none | read/write `location.search` | **Recommended** |
| B. Non-colliding path | `/board/<e>?opportunity=<o>` | SPA fallback in Vite (default in dev) and in whatever serves the build | parse `location.pathname` | Fine later; adds a fallback dependency now |
| C. Move API under `/api` | `/events/<e>?opportunity=<o>` | Serve mount `/api` (prefix stripped [12]), Vite proxy change, every `api.ts` path | as B | Most churn; only worth it with a router |
| D. Hash | `/#/event/<e>?opportunity=<o>` | none | `hashchange` | Works, but uglier than A for no gain |
| E. Add a router (react-router etc.) | any | as B | dependency + route tree | Overkill for two views |

### Minimum change for option A (sketch, not applied)

```ts
// lib/location.ts
export type AppLocation = { eventId: string | null; opportunityId: string | null };

export function readLocation(): AppLocation {
  const p = new URLSearchParams(window.location.search);
  return { eventId: p.get("event"), opportunityId: p.get("opportunity") };
}

export function writeLocation(loc: AppLocation, mode: "push" | "replace" = "push") {
  const p = new URLSearchParams();
  if (loc.eventId) p.set("event", loc.eventId);
  if (loc.eventId && loc.opportunityId) p.set("opportunity", loc.opportunityId);
  const qs = p.toString();
  const url = qs ? `/?${qs}` : "/";
  history[mode === "push" ? "pushState" : "replaceState"](null, "", url);
}
```

In `App.tsx`:

1. Initialise `selectedEventId` (and a new `pinnedOpportunityId`) from `readLocation()`.
2. A mount effect: if `selectedEventId` is set, `loadBoard(id)`; if `pinnedOpportunityId` is set, `GET /opportunities/{id}` for the banner. Both are DB reads and cost no credits (quota discipline holds: nothing refreshes).
3. `handleSelectEvent` -> `writeLocation({eventId, opportunityId: null})`; `handleBack` -> `writeLocation({eventId: null, opportunityId: null})`; dismissing the banner -> `writeLocation({...}, "replace")`.
4. `popstate` listener re-reads `readLocation()` and applies it, so browser back works.

The banner renders from the opportunity record. If it is gone (404) or no longer valid, the board still loads and the banner says so.

## 6. Service worker (sketch, not applied)

```js
// sw.js, registered at "/" scope
self.addEventListener("activate", (e) => e.waitUntil(self.clients.claim()));

// Runs on Chrome and pre-18.4 Safari. iOS/macOS 18.4+ handle a non-mutable
// declarative message without firing this.
self.addEventListener("push", (event) => {
  const n = event.data?.json()?.notification;
  if (!n) return;
  event.waitUntil(
    self.registration.showNotification(n.title, {
      body: n.body,
      tag: n.tag,
      data: { url: n.navigate }, // no `navigate` option: keep the click in our handler
    }),
  );
});

self.addEventListener("notificationclick", (event) => {
  event.notification.close();
  const target = new URL(event.notification.data?.url ?? "/", self.location.origin).href;
  event.waitUntil((async () => {
    const wins = await self.clients.matchAll({ type: "window", includeUncontrolled: true });
    const win = wins[0]; // most recently focused first
    if (win) {
      await win.focus(); // spend the click's activation first
      try {
        if (win.url !== target) await win.navigate(target);
        return;
      } catch {
        // uncontrolled or not yet ready: fall through
      }
    }
    await self.clients.openWindow(target);
  })());
});
```

Focus-then-navigate (rather than opening a second tab) matches the single-operator, single-window app. A full navigation reloads the page; that is acceptable because the page rebuilds its state from the URL. A `postMessage` + `pushState` alternative avoids the reload but adds a message handler and is exactly the path bug 252544 broke [9].

### Notifier payload (Web Push channel renders it)

```json
{
  "web_push": 8030,
  "notification": {
    "title": "Knicks ML +125 @ DraftKings",
    "body": "target +120 · fillable",
    "navigate": "https://<device>.<tailnet>.ts.net/?event=<eventId>&opportunity=<opportunityId>",
    "tag": "watch-<watchIntentId>"
  }
}
```

The origin comes from notifier config (e.g. `APP_PUBLIC_ORIGIN`), not from the event: the public CloudEvent carries IDs, the channel renders the URL (ADR-014). Keep `mutable` unset so 18.4+ devices never run the SW on this path.

## 7. Open uncertainties

| # | Uncertainty | How to close |
|---|---|---|
| 1 | Does a declarative `navigate` on iOS open the Home Screen app (not Safari) when the app is cold, backgrounded and the phone asleep? One report says navigation fails in that state (**second-hand**, bug 268797 comments) [10] | Device test on the operator's iPhone |
| 2 | Does iOS reuse the running web-app page or reload it on a declarative tap? (implementation-defined [5]) | Device test; the URL-driven SPA works either way |
| 3 | MDN compat says iOS has no `notificationclick`; WebKit's tracker says otherwise | Irrelevant if iOS stays on the declarative path |
| 4 | Desktop Chrome with an installed desktop PWA may open the URL in the app window rather than a tab [1][6] | Cosmetic; either lands on the same URL |
| 5 | How the built frontend is served in production behind Serve (Vite dev server vs static) is not decided | Option A works under both |

## Sources

1. MDN, `Clients.openWindow()`. https://developer.mozilla.org/en-US/docs/Web/API/Clients/openWindow
2. MDN, `WindowClient.navigate()` / `WindowClient.focus()`. https://developer.mozilla.org/en-US/docs/Web/API/WindowClient/navigate ; https://developer.mozilla.org/en-US/docs/Web/API/WindowClient/focus
   2b. W3C Service Workers (nightly): `openWindow(url)`, `navigate(url)`, `focus()` method steps; `matchAll` ordering ("most recently focused order"). https://w3c.github.io/ServiceWorker/
3. WebKit blog, "Meet Declarative Web Push" (iOS/iPadOS 18.4). https://webkit.org/blog/16535/meet-declarative-web-push/
4. W3C Push API: declarative push message parser, `mutable`, push message receipt steps. https://w3c.github.io/push-api/
5. WHATWG Notifications Standard, 2.7 "Activating a notification" and the `navigate` member. https://notifications.spec.whatwg.org/
6. MDN browser-compat-data (`api/ServiceWorkerGlobalScope.json`, `WindowClient.json`, `Clients.json`, `Notification.json`, `PushEvent.json`), fetched 2026-10-11. https://github.com/mdn/browser-compat-data
7. W3C Web Application Manifest: `scope`, `start_url`, navigation scope, "within scope". https://w3c.github.io/manifest/
8. WebKit blog, "Web Push for Web Apps on iOS and iPadOS". https://webkit.org/blog/13878/web-push-for-web-apps-on-ios-and-ipados/
9. WebKit bug 252544, "Initial ServiceWorkerWindowClient in a Home Screen web app launched to handle notificationclick handler is inert for a short period". https://bugs.webkit.org/show_bug.cgi?id=252544
10. WebKit bug 268797, "notificationclick events in serviceworkers not firing". https://bugs.webkit.org/show_bug.cgi?id=268797
11. WebKit bug 279456, "Clients.openWindow resolving promise too early". https://bugs.webkit.org/show_bug.cgi?id=279456
    11b. WebKit bug 279458, "WindowClient.matchAll resolves promise too early". https://bugs.webkit.org/show_bug.cgi?id=279458
12. Tailscale source, `ipn/ipnlocal/serve.go` (`getServeHandler`, `serveWebHandler`, `serveFileOrDirectory`). https://github.com/tailscale/tailscale/blob/main/ipn/ipnlocal/serve.go
13. WebKit blog, "WebKit Features in Safari 26.0" (Home Screen sites open as web apps by default). https://webkit.org/blog/17333/webkit-features-in-safari-26-0/
14. WebKit bug 259212, "clients.openWindow() not opening PWA home screen on iOS and macOS". https://bugs.webkit.org/show_bug.cgi?id=259212
15. web.dev (Chrome team), "Common notification patterns". https://web.dev/articles/push-notifications-common-notification-patterns
16. Tailscale KB, Serve. https://tailscale.com/kb/1312/serve
17. Tailscale KB, `tailscale serve` CLI (`--set-path`, `--https`). https://tailscale.com/kb/1242/tailscale-serve
