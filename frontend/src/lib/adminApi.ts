/**
 * The Admin view's calls, all under `/api/v1/admin` (ADR-018). One function per
 * endpoint; each Admin view feature adds its own types and functions here.
 */
import { request } from "./api";

const ADMIN = "/admin";

export type AutoRefreshOutcome = {
  sport: string;
  /** `refused`: the provider declined the call, out of credits. */
  status: RefreshOutcome;
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
  /** The newest upstream call was refused for credits. False before any call. */
  out_of_credits: boolean;
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

export type RefreshTrigger = "manual" | "auto";
export type RefreshOutcome = "succeeded" | "failed" | "refused";
/** Why a refresh did not succeed: a closed set. `error` carries the detail. */
export type RefreshErrorCode =
  | "UPSTREAM_HTTP"
  | "UPSTREAM_TIMEOUT"
  | "OUT_OF_USAGE_CREDITS"
  | "INVALID_RESPONSE"
  | "INTERNAL";

/** One refresh, manual or Auto-Refresh. `event_id` is null for a sport-wide refresh. */
export type RefreshRecord = {
  scope: "sport" | "event";
  sport: string;
  event_id: string | null;
  trigger: RefreshTrigger;
  started_at: string;
  finished_at: string;
  outcome: RefreshOutcome;
  error_code: RefreshErrorCode | null;
  error: string | null;
  events_refreshed: number;
  /**
   * What the upstream call it used spent. `null` when no call is linked: it made
   * none, or the call was not recorded. Refreshes
   * coalesced onto one call each show that call's cost; it was billed once.
   */
  credits_spent: number | null;
};

export type RefreshPage = {
  refreshes: RefreshRecord[];
  page: number;
  page_size: number;
  total_items: number;
  total_pages: number;
};

export type RefreshQuery = {
  sport?: string;
  trigger?: RefreshTrigger;
  outcome?: RefreshOutcome;
  error_code?: RefreshErrorCode;
  page?: number;
  page_size?: number;
};

/** The refresh log, newest first. A stored read: it never refreshes or spends credits. */
export async function getRefreshes(query: RefreshQuery = {}) {
  const params = new URLSearchParams();
  for (const [key, value] of Object.entries(query)) {
    if (value !== undefined && value !== "") params.set(key, String(value));
  }
  const search = params.toString();
  return request<RefreshPage>(`${ADMIN}/refreshes${search ? `?${search}` : ""}`);
}

export type DeliveryStatus = "pending" | "delivered" | "failed" | "expired" | "gone";

/**
 * One notification delivery. The device shows as its label and channel only and
 * the event as a short subject: never the push address, keys or raw payload.
 */
export type Delivery = {
  id: string;
  event_id: string;
  event_type: string;
  subject: string;
  destination_id: string;
  destination_label: string;
  channel: string;
  status: DeliveryStatus;
  attempts: number;
  last_error: string | null;
  created_at: string;
  /** When it reached its final status; `null` while pending. */
  ended_at: string | null;
};

export type DeliveryPage = {
  deliveries: Delivery[];
  page: number;
  page_size: number;
  total_items: number;
  total_pages: number;
};

export type DeliveryQuery = {
  status?: DeliveryStatus;
  event_type?: string;
  destination_id?: string;
  page?: number;
  page_size?: number;
};

/** Newest first. A database read: it never reaches upstream. */
export async function getDeliveries(query: DeliveryQuery = {}) {
  const params = new URLSearchParams();
  for (const [key, value] of Object.entries(query)) {
    if (value !== undefined) params.set(key, String(value));
  }
  const search = params.toString();
  return request<DeliveryPage>(`${ADMIN}/deliveries${search ? `?${search}` : ""}`);
}

/** The last remaining balance observed in one UTC hour. */
export type QuotaHistoryPoint = { hour: string; remaining: number };

/** Hourly points, oldest first; an hour with no upstream call has no point. */
export type QuotaHistory = { days: number; points: QuotaHistoryPoint[] };

/** The balance over the last `days` days (1-30). A stored read; spends nothing. */
export async function getQuotaHistory(days = 30) {
  return request<QuotaHistory>(`${ADMIN}/quota-history?days=${days}`);
}

export type UpstreamCallKind = "sport" | "event" | "balance_check";

/** One UTC month of spend, counted per upstream call, most credits first. */
export type CreditBurn = {
  month: string;
  starts_at: string;
  ends_at: string;
  total_credits: number;
  total_calls: number;
  by_sport: { sport: string; credits: number; calls: number }[];
  /** Balance checks name no sport, so they show here only. */
  by_kind: { kind: UpstreamCallKind; credits: number; calls: number }[];
};

/** Credits spent in `month` (`YYYY-MM`, UTC); the current month when omitted. */
export async function getCreditBurn(month?: string) {
  return request<CreditBurn>(`${ADMIN}/credit-burn${month ? `?month=${month}` : ""}`);
}

export type ComponentName = "database" | "notifier" | "provider";
/** Each component uses only the words its signal can prove. */
export type ComponentState = "healthy" | "unhealthy" | "connected" | "disconnected" | "unknown";

export type ComponentStatus = {
  component: ComponentName;
  state: ComponentState;
  observed_at: string;
};

/** The API row is not here: the UI shows it from whether this call got an answer. */
export async function getComponentStatus() {
  return request<{ components: ComponentStatus[] }>(`${ADMIN}/component-status`);
}

/** Facts from stored records, shown as they are; never judged against a threshold. */
export type Metrics = {
  last_successful_refresh: {
    scope: "sport" | "event";
    sport: string;
    event_id: string | null;
    finished_at: string;
  } | null;
  /** `null` before any upstream call. `below_floor` drives the attention pill. */
  credits: {
    remaining: number | null;
    used: number | null;
    floor: number | null;
    out_of_credits: boolean;
    below_floor: boolean;
    observed_at: string;
  } | null;
  /** Delivery counts cover deliveries created since this time (the last 24h). */
  deliveries_since: string;
  delivery_counts: { status: DeliveryStatus; count: number }[];
  pending_deliveries: { count: number; oldest_created_at: string | null };
};

/** A database read: it never reaches upstream. */
export async function getMetrics() {
  return request<Metrics>(`${ADMIN}/metrics`);
}
