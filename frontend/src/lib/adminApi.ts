/**
 * The Admin view's calls, all under `/api/v1/admin` (ADR-018). One function per
 * endpoint; each Admin view feature adds its own types and functions here.
 */
import { request } from "./api";

const ADMIN = "/admin";

export type AutoRefreshOutcome = {
  sport: string;
  status: "succeeded" | "failed";
  at: string;
  events_refreshed: number;
  error: string | null;
};

/** The latest credit balance seen upstream; `floor` is the one in force. */
export type Quota = {
  remaining: number | null;
  used: number | null;
  floor: number | null;
  source: "headers" | "local";
  observed_at: string;
};

/** The operator's switch. Turning it on spends nothing by itself; the worker does. */
export type AutoRefresh = {
  enabled: boolean;
  interval_minutes: number;
  /** The operator's warn-below floor; `null` means derive it (10% of the plan). */
  quota_floor: number | null;
  last_outcome: AutoRefreshOutcome | null;
  /** Out of credits: still on, but nothing paid is pulled until credits return. */
  paused: boolean;
  quota: Quota | null;
};

export type AutoRefreshSettings = Pick<AutoRefresh, "enabled" | "interval_minutes" | "quota_floor">;

export async function getAutoRefresh() {
  return request<AutoRefresh>(`${ADMIN}/auto-refresh`);
}

/**
 * Settings only, as a full replacement. The API never refreshes on this call; the
 * Auto-Refresh worker's next poll does, and only for sports with a watch to serve.
 */
export async function putAutoRefresh(settings: AutoRefreshSettings) {
  return request<AutoRefresh>(`${ADMIN}/auto-refresh`, {
    method: "PUT",
    body: JSON.stringify(settings)
  });
}
