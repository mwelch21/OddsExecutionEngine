import { useEffect, useRef, useState } from "react";
import {
  getComponentStatus,
  getMetrics,
  type ComponentState,
  type ComponentStatus,
  type Metrics
} from "../../../lib/adminApi";
import type { AdminTab } from "../../../lib/deepLink";

/**
 * Component status and operational metrics (#106). `apiReachable` is the API row:
 * whether the Admin view's own request got an answer; `null` while the first one
 * is out. The two reads land independently, so a slow metrics call never holds
 * back a component failure. Both are database reads; neither reaches the provider.
 */
export type SystemStatus = {
  apiReachable: boolean | null;
  components: ComponentStatus[] | null;
  metrics: Metrics | null;
  metricsUnavailable: boolean;
};

const CHECKING: SystemStatus = {
  apiReachable: null,
  components: null,
  metrics: null,
  metricsUnavailable: false
};

/** A call with no answer by then counts as no answer: the API row turns Unhealthy. */
const REQUEST_TIMEOUT_MS = 10_000;

const INVALIDATE_EVENT = "oddsengine:system-status-invalidated";

/** States that need the operator: the attention pill and the card colour share them. */
export const PROBLEM_STATES: ReadonlySet<ComponentState> = new Set(["unhealthy", "disconnected"]);

/**
 * Ask every status reader on the page to read again. Call it after anything that
 * can change a component or a metric: a refresh (failed ones too) or a floor edit.
 */
export function invalidateSystemStatus() {
  window.dispatchEvent(new Event(INVALIDATE_EVENT));
}

/**
 * The attention rule (#92): a component Unhealthy or Disconnected opens Systems;
 * credits below the floor open Credits. A component problem wins: it is the one
 * that stops things working.
 */
export function attentionTab(status: SystemStatus): AdminTab | null {
  if (status.apiReachable === false) return "systems";
  if (status.components?.some(({ state }) => PROBLEM_STATES.has(state))) return "systems";
  if (status.metrics?.credits?.below_floor) return "credits";
  return null;
}

/**
 * Reads on mount, whenever `key` changes, on window focus and on
 * `invalidateSystemStatus()`. No timer: a stale card is fixed by looking again,
 * not by polling. A newer read aborts the one before it, and a superseded answer
 * is dropped, so an old response never overwrites a newer one.
 */
export function useSystemStatus(key: unknown = null) {
  const [status, setStatus] = useState<SystemStatus>(CHECKING);
  const generation = useRef(0);

  useEffect(() => {
    let inFlight: AbortController | null = null;

    const read = () => {
      inFlight?.abort();
      const controller = new AbortController();
      inFlight = controller;
      const timer = window.setTimeout(() => controller.abort(), REQUEST_TIMEOUT_MS);
      const current = ++generation.current;
      const isCurrent = () => generation.current === current;

      const components = getComponentStatus(controller.signal).then(
        (response) => {
          if (isCurrent())
            setStatus((prev) => ({ ...prev, apiReachable: true, components: response.components }));
        },
        () => {
          // Aborted by a newer read: that read answers instead.
          if (isCurrent()) setStatus((prev) => ({ ...prev, apiReachable: false, components: null }));
        }
      );
      const metrics = getMetrics(controller.signal).then(
        (response) => {
          if (isCurrent()) setStatus((prev) => ({ ...prev, metrics: response, metricsUnavailable: false }));
        },
        () => {
          if (isCurrent()) setStatus((prev) => ({ ...prev, metrics: null, metricsUnavailable: true }));
        }
      );
      void Promise.allSettled([components, metrics]).then(() => window.clearTimeout(timer));
    };

    read();
    window.addEventListener("focus", read);
    window.addEventListener(INVALIDATE_EVENT, read);
    return () => {
      // Drops any answer still out, from this effect or an earlier one.
      generation.current += 1;
      inFlight?.abort();
      window.removeEventListener("focus", read);
      window.removeEventListener(INVALIDATE_EVENT, read);
    };
  }, [key]);

  return status;
}
