import React from "react";
import ReactDOM from "react-dom/client";
import { App } from "./App";
import { NotificationPrototype } from "./prototype/notifications/NotificationPrototype";
import "./styles.css";

ReactDOM.createRoot(document.getElementById("root") as HTMLElement).render(
  <React.StrictMode>
    {/* PROTOTYPE ONLY: ?proto=notify mounts the notification-UI prototype (dev builds only). */}
    {import.meta.env.DEV && new URLSearchParams(window.location.search).get("proto") === "notify" ? (
      <NotificationPrototype />
    ) : (
      <App />
    )}
  </React.StrictMode>
);
