import type { ReactNode } from "react";
import type { DeliveryStatus, Metrics } from "../../../lib/adminApi";
import { ageLabel } from "../../../lib/format";
import { EmptyState, Pill } from "../../primitives";
import { AdminPanel } from "../AdminPanel";

const STATUS_TONE: Record<DeliveryStatus, "good" | "warn" | "neutral"> = {
  pending: "neutral",
  delivered: "good",
  failed: "warn",
  expired: "warn",
  gone: "warn"
};

function credit(value: number | null | undefined) {
  return value === null || value === undefined ? "--" : value.toLocaleString();
}

/**
 * Operational metrics (#106): facts read from stored records, shown as they are.
 * Nothing here is judged against a threshold except the credit floor the operator
 * set, and that only colours the number.
 */
export function MetricsPanel({ metrics, unavailable }: { metrics: Metrics | null; unavailable: boolean }) {
  return (
    <AdminPanel title="Operational metrics">
      {!metrics ? (
        unavailable ? <p className="admin-warn">Metrics are unavailable.</p> : <EmptyState>Loading</EmptyState>
      ) : (
        <dl className="metrics-grid">
          <Metric label="Last successful refresh">
            {metrics.last_successful_refresh ? (
              <>
                <strong>{ageLabel(metrics.last_successful_refresh.finished_at)}</strong>
                <span className="admin-muted">
                  {metrics.last_successful_refresh.sport}
                  {metrics.last_successful_refresh.scope === "event" && " · one event"}
                </span>
              </>
            ) : (
              <span className="admin-muted">No refresh has succeeded yet</span>
            )}
          </Metric>

          <Metric label="Credits remaining">
            {metrics.credits ? (
              <>
                <strong className={metrics.credits.below_floor ? "metric-warn" : undefined}>
                  {credit(metrics.credits.remaining)}
                </strong>
                <span className="admin-muted">
                  {credit(metrics.credits.used)} used · floor {credit(metrics.credits.floor)}
                  {metrics.credits.out_of_credits && " · out of credits"}
                </span>
              </>
            ) : (
              <span className="admin-muted">No upstream call yet</span>
            )}
          </Metric>

          <Metric label="Deliveries, last 24h">
            <div className="metric-pills">
              {metrics.delivery_counts.map(({ status, count }) => (
                <Pill key={status} tone={count > 0 ? STATUS_TONE[status] : "neutral"}>
                  {count} {status}
                </Pill>
              ))}
            </div>
          </Metric>

          <Metric label="Pending deliveries">
            <strong>{metrics.pending_deliveries.count}</strong>
            <span className="admin-muted">
              {metrics.pending_deliveries.oldest_created_at
                ? `oldest queued ${ageLabel(metrics.pending_deliveries.oldest_created_at)}`
                : "none waiting"}
            </span>
          </Metric>
        </dl>
      )}
    </AdminPanel>
  );
}

function Metric({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="metric">
      <dt>{label}</dt>
      <dd>{children}</dd>
    </div>
  );
}
