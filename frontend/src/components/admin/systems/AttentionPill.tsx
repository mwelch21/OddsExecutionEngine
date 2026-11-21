import { AlertTriangle } from "lucide-react";
import type { AdminTab } from "../../../lib/deepLink";
import { attentionTab, useSystemStatus } from "./systemStatus";

/**
 * The top-bar attention pill (#92): shown only while a component is Unhealthy or
 * Disconnected, or credits are below the floor, and opens the tab that says why.
 * Re-read on each navigation (`routeKey`) and on window focus, never on a timer.
 */
export function AttentionPill({
  routeKey,
  onOpen
}: {
  routeKey: string;
  onOpen: (tab: AdminTab) => void;
}) {
  const status = useSystemStatus(routeKey);
  const tab = attentionTab(status);
  if (!tab) return null;
  return (
    <button type="button" className="pill pill-warn attention-pill" onClick={() => onOpen(tab)}>
      <AlertTriangle size={14} />
      {tab === "credits" ? "Credits low" : "Needs attention"}
    </button>
  );
}
