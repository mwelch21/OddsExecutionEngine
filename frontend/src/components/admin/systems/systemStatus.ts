import { useEffect, useState } from "react";
import {
  getComponentStatus,
  getMetrics,
  type ComponentState,
  type ComponentStatus,
  type Metrics
} from "../../../lib/adminApi";
import type { AdminTab } from "../../../lib/deepLink";

/**
 * Component status and operational metrics as one read (#106). `apiReachable` is
 * the API row: whether the Admin view's own request got an answer. Both calls are
 * database reads; neither ever reaches the odds provider.
 */
export type SystemStatus = {
  apiReachable: boolean;
  components: ComponentStatus[] | null;
  metrics: Metrics | null;
};

/** States that need the operator: the attention pill and the card colour share them. */
export const PROBLEM_STATES: ReadonlySet<ComponentState> = new Set(["unhealthy", "disconnected"]);

export async function readSystemStatus(): Promise<SystemStatus> {
  const [components, metrics] = await Promise.allSettled([getComponentStatus(), getMetrics()]);
  return {
    apiReachable: components.status === "fulfilled",
    components: components.status === "fulfilled" ? components.value.components : null,
    metrics: metrics.status === "fulfilled" ? metrics.value : null
  };
}

/**
 * The attention rule (#92): a component Unhealthy or Disconnected opens Systems;
 * credits below the floor open Credits. A component problem wins: it is the one
 * that stops things working.
 */
export function attentionTab(status: SystemStatus | null): AdminTab | null {
  if (!status) return null;
  if (!status.apiReachable) return "systems";
  if (status.components?.some(({ state }) => PROBLEM_STATES.has(state))) return "systems";
  if (status.metrics?.credits?.below_floor) return "credits";
  return null;
}

/**
 * Reads on mount, whenever `key` changes and when the window regains focus. No
 * timer: a stale card is fixed by looking again, not by polling.
 */
export function useSystemStatus(key: unknown = null) {
  const [status, setStatus] = useState<SystemStatus | null>(null);

  useEffect(() => {
    let cancelled = false;
    // Never rejects: a call that fails shows as its own Unhealthy or missing row.
    const read = () => {
      void readSystemStatus().then((next) => {
        if (!cancelled) setStatus(next);
      });
    };
    read();
    window.addEventListener("focus", read);
    return () => {
      cancelled = true;
      window.removeEventListener("focus", read);
    };
  }, [key]);

  return status;
}
