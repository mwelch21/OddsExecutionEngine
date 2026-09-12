import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

const apiTarget = process.env.FRONTEND_API_TARGET ?? "http://localhost:8000";

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      "/health": apiTarget,
      "/execution": apiTarget,
      "/ingestion": apiTarget,
      "/watch-intents": apiTarget,
      "/opportunities": apiTarget
    }
  }
});
