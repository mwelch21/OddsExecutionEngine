// Web Push registration: turns this browser into a destination.
//
// iOS only allows this from the home-screen app (iOS 16.4+), and every browser
// requires the permission prompt to come from a user tap, so `enablePush` must
// be called straight from a click handler.

export type PushSupport = "supported" | "unsupported" | "needs-install";

export type Destination = {
  id: string;
  channel: "web_push";
  label: string;
  address: string;
  active: boolean;
  created_at: string | null;
  last_delivered_at: string | null;
  disabled_at: string | null;
  disabled_reason: "user_removed" | "gone" | null;
};

const SERVICE_WORKER_URL = "/sw.js";

export function pushSupport(): PushSupport {
  const capable =
    "serviceWorker" in navigator && "PushManager" in window && "Notification" in window;
  if (capable) return "supported";
  // Safari on iOS hides PushManager until the app runs from the home screen.
  const isIos = /iPhone|iPad|iPod/.test(navigator.userAgent);
  return isIos ? "needs-install" : "unsupported";
}

export function registerServiceWorker(): void {
  if (!("serviceWorker" in navigator)) return;
  navigator.serviceWorker.register(SERVICE_WORKER_URL).catch((error: unknown) => {
    console.warn("Service worker registration failed", error);
  });
}

/** The subscription this browser already holds, if any, as a stored destination address. */
export async function currentSubscriptionEndpoint(): Promise<string | null> {
  if (pushSupport() !== "supported") return null;
  const registration = await navigator.serviceWorker.getRegistration(SERVICE_WORKER_URL);
  const subscription = await registration?.pushManager.getSubscription();
  return subscription?.endpoint ?? null;
}

export async function enablePush(): Promise<Destination> {
  if (pushSupport() !== "supported") {
    throw new Error("This browser cannot receive push notifications.");
  }
  const permission = await Notification.requestPermission();
  if (permission !== "granted") {
    throw new Error("Notifications were not allowed.");
  }

  const keyResponse = await fetch("/push/vapid-public-key");
  if (!keyResponse.ok) {
    throw new Error("Push is not configured on the server (VAPID_PUBLIC_KEY).");
  }
  const { public_key: publicKey } = (await keyResponse.json()) as { public_key: string };

  const registration = await navigator.serviceWorker.register(SERVICE_WORKER_URL);
  await navigator.serviceWorker.ready;
  const subscription = await registration.pushManager.subscribe({
    userVisibleOnly: true,
    applicationServerKey: base64UrlToBytes(publicKey)
  });

  const response = await fetch("/destinations/web-push", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ ...subscription.toJSON(), label: deviceLabel() })
  });
  if (!response.ok) {
    throw new Error(`Registering this device failed: ${response.status}`);
  }
  return (await response.json()) as Destination;
}

export async function listDestinations(): Promise<Destination[]> {
  const response = await fetch("/destinations");
  if (!response.ok) throw new Error(`/destinations failed: ${response.status}`);
  return ((await response.json()) as { destinations: Destination[] }).destinations;
}

function deviceLabel(): string {
  const agent = navigator.userAgent;
  if (/iPhone/.test(agent)) return "iPhone";
  if (/iPad/.test(agent)) return "iPad";
  if (/Android/.test(agent)) return "Android";
  if (/Macintosh/.test(agent)) return "Mac";
  if (/Windows/.test(agent)) return "Windows";
  return "Browser";
}

function base64UrlToBytes(value: string): Uint8Array<ArrayBuffer> {
  const padded = value + "=".repeat((4 - (value.length % 4)) % 4);
  const binary = atob(padded.replace(/-/g, "+").replace(/_/g, "/"));
  const bytes = new Uint8Array(new ArrayBuffer(binary.length));
  for (let i = 0; i < binary.length; i += 1) bytes[i] = binary.charCodeAt(i);
  return bytes;
}
