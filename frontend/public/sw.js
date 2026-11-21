// Service worker for Web Push.
//
// Every push MUST show a notification. iOS revokes a subscription whose pushes
// arrive silently, so even an unreadable payload falls back to a generic one.

self.addEventListener("install", () => self.skipWaiting());
self.addEventListener("activate", (event) => event.waitUntil(self.clients.claim()));

self.addEventListener("push", (event) => {
  let message = {};
  try {
    message = event.data ? event.data.json() : {};
  } catch {
    message = { body: event.data ? event.data.text() : "" };
  }
  // Declarative Web Push (iOS 18.4+) nests the notification under `notification`.
  const notification = message.notification ?? message;
  const title = notification.title || "OddsCafe";
  event.waitUntil(
    self.registration.showNotification(title, {
      body: notification.body || "",
      tag: notification.tag,
      data: { url: notification.navigate || notification.url || "/" }
    })
  );
});

// Desktop Chrome, and Safari before 18.4, land here. Declarative pushes on iOS
// and Safari 18.4+ are navigated by the OS and never reach this handler.
self.addEventListener("notificationclick", (event) => {
  event.notification.close();
  event.waitUntil(openApp(event.notification.data?.url || "/"));
});

// Reuse the most recently focused app window rather than opening a second one.
// The click grants the user activation that focus() and openWindow() need.
async function openApp(url) {
  const target = new URL(url, self.location.origin).href;
  const windows = await self.clients.matchAll({ type: "window", includeUncontrolled: true });
  const existing = windows[0];
  if (existing) {
    try {
      const focused = await existing.focus();
      await focused.navigate(target);
      return;
    } catch {
      // navigate() rejects for an uncontrolled window; fall through to a new one.
    }
  }
  await self.clients.openWindow(target);
}
