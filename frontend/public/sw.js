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

self.addEventListener("notificationclick", (event) => {
  event.notification.close();
  // Focus-and-navigate an existing window is the "Desktop tap landing" ticket.
  event.waitUntil(self.clients.openWindow(event.notification.data?.url || "/"));
});
