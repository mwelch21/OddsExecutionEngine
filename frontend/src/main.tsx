import React from "react";
import ReactDOM from "react-dom/client";
import { AdminLayoutPrototype } from "./prototype/AdminLayoutPrototype";
import { registerServiceWorker } from "./lib/push";
import "./styles.css";

registerServiceWorker();

ReactDOM.createRoot(document.getElementById("root") as HTMLElement).render(
  <React.StrictMode>
    <AdminLayoutPrototype />
  </React.StrictMode>
);
