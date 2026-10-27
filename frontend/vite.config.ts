import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Ports come from the environment so a second worktree can run its own stack.
// The defaults are slot 0 — the values this repo has always used — so running
// without a .env is unchanged.
//
// strictPort matters: without it Vite silently walks to the next free port when
// slot 0 is taken, which is exactly the collision this is meant to prevent and
// would leave the stack listening somewhere nobody expects.
const apiPort = process.env.APP_PORT ?? "8000";
const frontendPort = Number(process.env.FRONTEND_PORT ?? 5173);
const apiTarget = process.env.FRONTEND_API_TARGET ?? `http://localhost:${apiPort}`;

export default defineConfig({
  plugins: [react()],
  server: {
    port: frontendPort,
    strictPort: true,
    // Tailscale Serve proxies https://<machine>.<tailnet>.ts.net to this server so
    // the iPhone gets the HTTPS that Web Push requires. Vite rejects unknown Host
    // headers by default, so tailnet names are allowed explicitly.
    allowedHosts: [".ts.net"],
    proxy: {
      "/health": apiTarget,
      "/execution": apiTarget,
      "/ingestion": apiTarget,
      "/events": apiTarget,
      "/sports": apiTarget,
      "/watch-intents": apiTarget,
      "/opportunities": apiTarget,
      "/push": apiTarget,
      "/destinations": apiTarget,
      "/auto-refresh": apiTarget
    }
  }
});
