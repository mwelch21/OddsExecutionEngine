# Web Push on the operator's devices

How to get notifications onto the iPhone (and desktop) in v1. The stack runs on
the operator's MacBook (#65) and is reached over the tailnet; nothing is exposed
to the public internet.

## 1. Generate the VAPID keys (once)

```bash
uv run python scripts/generate_vapid_keys.py --subject mailto:you@example.com
```

This writes `VAPID_PUBLIC_KEY`, `VAPID_PRIVATE_KEY` and `VAPID_SUBJECT` into `.env`
(git-ignored, mode 600). The script refuses to overwrite existing keys.

- The **API** receives only `VAPID_PUBLIC_KEY` (see `docker-compose.yml`). Never
  add `VAPID_PRIVATE_KEY` to the api service.
- The **notifier** is the only service that receives `VAPID_PRIVATE_KEY`.

Restart the API afterwards (`just refresh`) and check:

```bash
curl -s localhost:8000/push/vapid-public-key
```

### Rotating keys

There is no automatic rotation. `--force` replaces the pair, and **every existing
subscription stops working** until each device taps "Enable notifications" again.
Only rotate if the private key may have leaked.

## 2. Serve the app over HTTPS with Tailscale Serve

Web Push needs HTTPS (desktop `localhost` is exempt; the iPhone is not).

1. Install Tailscale on the Mac and the iPhone, and sign both into the same tailnet.
2. In the Tailscale admin console, enable **MagicDNS** and **HTTPS certificates**.
3. With the stack running (`just dev`), serve the frontend:

   ```bash
   tailscale serve --bg 5173
   tailscale serve status   # prints https://<machine>.<tailnet>.ts.net
   ```

   The Vite dev server proxies the API paths, so one HTTPS origin serves both.
   `tailscale serve reset` turns it off.

## 3. Install on the iPhone and subscribe

Requires **iOS 16.4 or later**. Push only works from the home-screen app, never
from a Safari tab.

1. On the iPhone, open `https://<machine>.<tailnet>.ts.net` in Safari.
2. Share → **Add to Home Screen**, keep "Open as Web App" on.
3. Open **OddsCafe from the home screen**.
4. Tap **Enable notifications** and allow the prompt.
5. The pill changes to "Notifications on". Confirm the device is stored:

   ```bash
   curl -s localhost:8000/destinations
   ```

In a Safari tab the app shows "Add to Home Screen to get notifications" instead
of the button.

## 4. Desktop

Open the app (`http://localhost:5173`, or the tailnet URL) in Chrome, Edge,
Firefox or Safari and tap **Enable notifications**. Each browser is its own
destination.

## Limits in v1

- Notifications arrive only while the Mac is awake, online, and running the stack.
- A test notification and real deliveries arrive once the notifier ships
  ("Send a test notification end to end").
