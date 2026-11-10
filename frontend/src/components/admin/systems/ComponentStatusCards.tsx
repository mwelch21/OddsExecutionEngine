import { Bell, Database, RadioTower, Server } from "lucide-react";
import type { ReactNode } from "react";
import type { ComponentName, ComponentState } from "../../../lib/adminApi";
import { ageLabel } from "../../../lib/format";
import { Pill } from "../../primitives";
import { PROBLEM_STATES, type SystemStatus } from "./systemStatus";

type Card = {
  key: "api" | ComponentName;
  label: string;
  icon: ReactNode;
  /** What the state proves, so a reader never takes Connected for "delivering". */
  signal: string;
};

const CARDS: Card[] = [
  { key: "api", label: "API", icon: <Server size={18} />, signal: "This page's request got an answer" },
  { key: "database", label: "Database", icon: <Database size={18} />, signal: "SELECT 1 answered" },
  {
    key: "notifier",
    label: "Notifier",
    icon: <Bell size={18} />,
    signal: "Its listener connection is open"
  },
  {
    key: "provider",
    label: "Odds provider",
    icon: <RadioTower size={18} />,
    signal: "The newest upstream call got a usable answer"
  }
];

const LABELS: Record<ComponentState, string> = {
  healthy: "Healthy",
  unhealthy: "Unhealthy",
  connected: "Connected",
  disconnected: "Disconnected",
  unknown: "Unknown"
};

function tone(state: ComponentState): "good" | "warn" | "neutral" {
  if (PROBLEM_STATES.has(state)) return "warn";
  return state === "unknown" ? "neutral" : "good";
}

/**
 * One card per component (#106), each read straight from one signal. No combined
 * verdict: four separate facts.
 */
export function ComponentStatusCards({ status }: { status: SystemStatus }) {
  return (
    <div className="status-cards" aria-label="Component status">
      {CARDS.map((card) => {
        const row = status?.components?.find(({ component }) => component === card.key);
        // The API row is UI-side; with no answer, the others cannot be read.
        const state: ComponentState | null =
          status.apiReachable === null
            ? null
            : card.key === "api"
              ? status.apiReachable
                ? "healthy"
                : "unhealthy"
              : (row?.state ?? "unknown");
        // The provider's time is its newest answer; with none yet there is no age to show.
        const seen =
          card.key === "provider" && row && row.state !== "unknown" ? ageLabel(row.observed_at) : null;
        return (
          <section key={card.key} className={`status-card${state && tone(state) === "warn" ? " status-card-problem" : ""}`}>
            <div className="status-card-heading">
              {card.icon}
              <h3>{card.label}</h3>
            </div>
            {state ? <Pill tone={tone(state)}>{LABELS[state]}</Pill> : <Pill>Checking</Pill>}
            <span className="admin-muted">
              {card.signal}
              {seen && ` · ${seen}`}
            </span>
          </section>
        );
      })}
    </div>
  );
}
