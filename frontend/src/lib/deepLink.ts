/**
 * The app's location, kept in the root URL's query string.
 *
 * There is no router on purpose: `/events` is an API prefix the dev proxy sends
 * to FastAPI, and Tailscale Serve has no SPA fallback, so every screen lives at
 * `/` and differs only by `?event=<id>&opportunity=<id>`. That is also the shape
 * the notifier links to, so a tapped notification and a reload land the same way.
 */
export type DeepLink = {
  eventId: string | null;
  opportunityId: string | null;
};

export function readDeepLink(search: string = window.location.search): DeepLink {
  const params = new URLSearchParams(search);
  const eventId = params.get("event") || null;
  // An opportunity is only ever shown pinned above its event's board.
  const opportunityId = eventId ? params.get("opportunity") || null : null;
  return { eventId, opportunityId };
}

export function deepLinkUrl({ eventId, opportunityId }: DeepLink) {
  const params = new URLSearchParams();
  if (eventId) params.set("event", eventId);
  if (eventId && opportunityId) params.set("opportunity", opportunityId);
  const query = params.toString();
  return query ? `/?${query}` : "/";
}

/** A new history entry, so the browser's Back button retraces navigation. */
export function pushDeepLink(link: DeepLink) {
  window.history.pushState(null, "", deepLinkUrl(link));
}

/** Rewrites the current entry, for changes Back should not step through. */
export function replaceDeepLink(link: DeepLink) {
  window.history.replaceState(null, "", deepLinkUrl(link));
}
