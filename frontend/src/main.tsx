import React from "react";
import ReactDOM from "react-dom/client";
import { AdminNavPrototype } from "./prototype/AdminNavPrototype";
import { registerServiceWorker } from "./lib/push";
import "./styles.css";

registerServiceWorker();

ReactDOM.createRoot(document.getElementById("root") as HTMLElement).render(
  <React.StrictMode>
    <AdminNavPrototype />
  </React.StrictMode>
);
