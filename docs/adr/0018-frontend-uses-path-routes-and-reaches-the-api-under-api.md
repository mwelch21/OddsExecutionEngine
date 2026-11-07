# ADR-018: The frontend uses path routes and reaches the API under `/api/v1`

- Status: accepted
- Date: 2026-11-06

## Context

The frontend and the API share one origin: the Vite dev server in development, with Tailscale Serve in front of it for the iPhone. The dev proxy forwards API prefixes such as `/events`, `/destinations` and `/auto-refresh` to FastAPI by path. Because `/events` was already an API prefix, the deep-link decision (#66) put every screen at `/` and told screens apart by query string (`/?event=<id>&opportunity=<id>`), with no router.

The Admin view (#90) adds a whole page with three tabs. Squeezing it into query params (`/?view=admin&tab=credits`) works, but it bends frontend navigation around a proxy rule, and every new backend prefix would be another path the UI can never use.

## Decision

- **One versioned API path, the same everywhere** (amended 2026-11-07, #93). FastAPI mounts every router under `/api/v1`. The proxy (Vite in development, whatever fronts the app when hosted) forwards `/api/*` unchanged, with no prefix strip. The UI, the proxy and any future consumer use the same path. `/health` moves to `/api/health` and stays unversioned, because it is an ops probe, not contract.
- **Version policy.** `v1` is the only version. An additive change keeps `v1`. A breaking change adds a `/api/v2` router beside `v1`, and `v1` stays until no consumer uses it. This is the same rule as the public event contract (ADR-014). A deprecation process waits until a second consumer exists.
- **Operator routes under one prefix.** Auto-Refresh and the Admin view reads live under `/api/v1/admin`, so one hook can gate them when auth arrives (#14). Destinations stay outside it, because each device owner registers their own.
- **Path routes in the frontend.** Every non-`/api` path is served the app shell (SPA fallback), and the app reads `location.pathname`:
  - `/`: Home
  - `/events/<id>` (with optional `?opportunity=<id>`): the line board, with that opportunity pinned
  - `/admin/systems`, `/admin/credits`, `/admin/controls`: the Admin view tabs; `/admin` lands on Systems
- **Notification links follow the routes.** The notifier builds opportunity links as `/events/<id>?opportunity=<id>` and quota-warning links as `/admin/credits`. The event contract is unchanged; the channel builds the link (ADR-014).
- **Manifest scope stays `/`**, so every route opens inside the installed PWA.

## Rejected alternatives

- **Keep everything at `/` with query params:** works, but it makes the proxy's prefix list decide what the UI may call its pages.
- **Keep backend paths and strip `/api` in the proxy** (the first version of this ADR): avoids a one-time path break, but needs a rewrite rule in every proxy and leaves no place for a version. The operator is the only consumer today, so the break is cheapest now.
- **Separate hostnames for UI and API:** removes the clash, but adds CORS and a second Tailscale Serve name for no gain while the stack runs on one machine.

## Consequences

- Supersedes the root-plus-query-params part of #66. `deepLink.ts`, the frontend API client, the dev proxy and the notifier's link builder all change.
- Whatever serves the built frontend later (hosting is a separate effort) must forward `/api/*` unchanged and provide the SPA fallback.
- Links in notifications sent before the change point at `/?event=…`. The app keeps reading that form as a redirect until it no longer matters.
