import type { ReactNode } from "react";
import type { AutoRefresh } from "../../../lib/adminApi";
import { ageLabel } from "../../../lib/format";
import { EmptyState, Pill } from "../../primitives";
import { AdminPanel } from "../AdminPanel";

/**
 * Credits left against the plan, with the floor marked. Read from
 * `GET /api/v1/admin/auto-refresh`, whose quota is the newest upstream call's.
 */
export function CreditMeterPanel({
  status,
  error,
  actions
}: {
  status: AutoRefresh | null;
  error: string | null;
  actions: ReactNode;
}) {
  const quota = status?.quota ?? null;
  return (
    <AdminPanel title="Credits left" actions={actions}>
      {error && <p className="admin-warn">{error}</p>}
      {!status && !error && <p className="admin-muted">Loading…</p>}
      {status && quota === null && (
        <EmptyState>No upstream call yet. The balance shows after the first refresh.</EmptyState>
      )}
      {status && quota !== null && (
        <Meter
          remaining={quota.remaining}
          used={quota.used}
          floor={quota.floor}
          outOfCredits={status.out_of_credits}
          paused={status.paused}
          observedAt={quota.observed_at}
        />
      )}
      <p className="admin-muted">Resets {resetLabel(new Date())} (monthly, UTC).</p>
    </AdminPanel>
  );
}

function Meter({
  remaining,
  used,
  floor,
  outOfCredits,
  paused,
  observedAt
}: {
  remaining: number | null;
  used: number | null;
  floor: number | null;
  outOfCredits: boolean;
  paused: boolean;
  observedAt: string;
}) {
  const plan = remaining !== null && used !== null ? remaining + used : null;
  const share = plan ? (remaining ?? 0) / plan : null;
  const floorShare = plan && floor !== null ? Math.min(floor / plan, 1) : null;
  const low = remaining !== null && floor !== null && remaining < floor;

  return (
    <div className="credit-meter">
      <div className="credit-meter-figures">
        <strong className="credit-meter-remaining">{remaining ?? "—"}</strong>
        <span className="admin-muted">
          {plan !== null ? `of ${plan} left · ${used} used` : "remaining (plan size not reported)"}
        </span>
        {outOfCredits ? (
          <Pill tone="warn">out of credits</Pill>
        ) : low ? (
          <Pill tone="warn">below floor</Pill>
        ) : null}
        {paused && <Pill tone="warn">Auto-Refresh paused</Pill>}
      </div>
      {share !== null && (
        <div
          className="credit-meter-bar"
          role="meter"
          aria-label="Credits left"
          aria-valuemin={0}
          aria-valuemax={plan ?? 0}
          aria-valuenow={remaining ?? 0}
        >
          <div
            className={`credit-meter-fill${low || outOfCredits ? " low" : ""}`}
            style={{ width: `${share * 100}%` }}
          />
          {floorShare !== null && (
            <div
              className="credit-meter-floor"
              style={{ left: `${floorShare * 100}%` }}
              title={`Floor ${floor}`}
            />
          )}
        </div>
      )}
      <p className="admin-muted">
        Floor {floor ?? "not set"} · observed{" "}
        <time dateTime={observedAt} title={new Date(observedAt).toLocaleString()}>
          {ageLabel(observedAt) ?? observedAt}
        </time>
      </p>
    </div>
  );
}

/** The provider's credits renew each calendar month; the next reset is the 1st. */
function resetLabel(now: Date) {
  const next = new Date(Date.UTC(now.getUTCFullYear(), now.getUTCMonth() + 1, 1));
  return next.toLocaleDateString(undefined, { day: "numeric", month: "short", timeZone: "UTC" });
}
