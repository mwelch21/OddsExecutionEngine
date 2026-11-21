/**
 * The app's location, kept in the URL path (ADR-018).
 *
 * There is no router library: the app reads `location.pathname`.
 *
 * - `/`: Home
 * - `/events/<id>` (optional `?opportunity=<id>`): the line board, with that
 *   opportunity pinned
 * - `/admin/systems`, `/admin/credits`, `/admin/controls`: the Admin view tabs;
 *   `/admin` lands on Systems
 *
 * The whole API lives under `/api`, so no app path clashes with it. The notifier
 * links to these same routes, so a tapped notification and a reload land the
 * same way.
 */
export const ADMIN_TABS = ["systems", "credits", "controls"] as const;
export type AdminTab = (typeof ADMIN_TABS)[number];

export type Route =
  | { view: "home" }
  | { view: "event"; eventId: string; opportunityId: string | null }
  | { view: "admin"; tab: AdminTab };

export const HOME: Route = { view: "home" };

export function readRoute(location: Pick<Location, "pathname" | "search"> = window.location): Route {
  const params = new URLSearchParams(location.search);
  const segments = location.pathname.split("/").filter(Boolean).map(safeDecode);

  // Links sent before ADR-018 point at `/?event=<id>&opportunity=<id>`.
  if (segments.length === 0) {
    const legacyEventId = params.get("event");
    return legacyEventId ? eventRoute(legacyEventId, params.get("opportunity")) : HOME;
  }

  const [first, second, ...rest] = segments;
  if (first === "events" && second && rest.length === 0) {
    return eventRoute(second, params.get("opportunity"));
  }
  if (first === "admin" && rest.length === 0) {
    const tab = ADMIN_TABS.find((candidate) => candidate === (second ?? "systems"));
    if (tab) return { view: "admin", tab };
  }
  // Any other path gets the app shell; it falls back to Home.
  return HOME;
}

export function routeUrl(route: Route): string {
  switch (route.view) {
    case "home":
      return "/";
    case "event": {
      const path = `/events/${encodeURIComponent(route.eventId)}`;
      if (!route.opportunityId) return path;
      return `${path}?${new URLSearchParams({ opportunity: route.opportunityId })}`;
    }
    case "admin":
      return `/admin/${route.tab}`;
  }
}

/** A new history entry, so the browser's Back button retraces navigation. */
export function pushRoute(route: Route) {
  window.history.pushState(null, "", routeUrl(route));
}

/** Rewrites the current entry, for changes Back should not step through. */
export function replaceRoute(route: Route) {
  window.history.replaceState(null, "", routeUrl(route));
}

/**
 * Rewrites the current entry to the route's canonical URL: an old query link,
 * a bare `/admin` or an unknown path. Returns the route it settled on.
 */
export function canonicalizeLocation(): Route {
  const route = readRoute();
  const current = window.location.pathname + window.location.search;
  if (current !== routeUrl(route)) replaceRoute(route);
  return route;
}

function eventRoute(eventId: string, opportunityId: string | null): Route {
  return { view: "event", eventId, opportunityId: opportunityId || null };
}

function safeDecode(segment: string): string {
  try {
    return decodeURIComponent(segment);
  } catch {
    return segment;
  }
}
