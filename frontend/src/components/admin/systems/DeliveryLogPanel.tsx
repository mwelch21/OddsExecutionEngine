import { ChevronLeft, ChevronRight } from "lucide-react";
import { useEffect, useState } from "react";
import { getDeliveries, type Delivery, type DeliveryPage, type DeliveryStatus } from "../../../lib/adminApi";
import { ageLabel } from "../../../lib/format";
import { Button, EmptyState, Pill } from "../../primitives";
import { AdminPanel } from "../AdminPanel";

const PAGE_SIZE = 25;
const STATUSES: DeliveryStatus[] = ["pending", "delivered", "failed", "expired", "gone"];
const EVENT_TYPES: Record<string, string> = {
  "oddsengine.opportunity.identified.v1": "Opportunity",
  "oddsengine.destination.test.v1": "Test",
  "oddsengine.quota.warning.v1": "Quota warning"
};
/** Outcomes the operator should look at: the delivery ended without arriving. */
const PROBLEM: ReadonlySet<DeliveryStatus> = new Set(["failed", "expired", "gone"]);

function statusTone(status: DeliveryStatus): "good" | "warn" | "neutral" {
  if (status === "delivered") return "good";
  return PROBLEM.has(status) ? "warn" : "neutral";
}

/**
 * Every notification delivery, failures included (#105). It drives
 * `GET /api/v1/admin/deliveries` only, a database read that never spends credits.
 * Read when the tab opens and on each filter or page change; never polled.
 */
export function DeliveryLogPanel() {
  const [status, setStatus] = useState<DeliveryStatus | "">("");
  const [eventType, setEventType] = useState("");
  const [page, setPage] = useState(1);
  const [log, setLog] = useState<DeliveryPage | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    getDeliveries({
      status: status || undefined,
      event_type: eventType || undefined,
      page,
      page_size: PAGE_SIZE
    })
      .then((response) => {
        if (cancelled) return;
        setLog(response);
        setError(null);
      })
      .catch((reason: unknown) => {
        if (!cancelled) setError(reason instanceof Error ? reason.message : "Unavailable");
      });
    return () => {
      cancelled = true;
    };
  }, [status, eventType, page]);

  const filtered = status !== "" || eventType !== "";

  return (
    <AdminPanel
      title="Delivery log"
      actions={log && <span className="admin-muted">{log.total_items} total</span>}
    >
      <div className="admin-row">
        <label className="select-shell">
          Status
          <select
            value={status}
            onChange={(event) => {
              setStatus(event.target.value as DeliveryStatus | "");
              setPage(1);
            }}
          >
            <option value="">All</option>
            {STATUSES.map((value) => (
              <option key={value} value={value}>
                {value}
              </option>
            ))}
          </select>
        </label>
        <label className="select-shell">
          Event
          <select
            value={eventType}
            onChange={(event) => {
              setEventType(event.target.value);
              setPage(1);
            }}
          >
            <option value="">All</option>
            {Object.entries(EVENT_TYPES).map(([value, label]) => (
              <option key={value} value={value}>
                {label}
              </option>
            ))}
          </select>
        </label>
      </div>

      {error && <p className="admin-warn">{error}</p>}

      {log && log.deliveries.length === 0 ? (
        <EmptyState>
          {filtered
            ? "No deliveries match these filters."
            : "No notifications sent yet. Each delivery will show here."}
        </EmptyState>
      ) : (
        <ul className="delivery-log">
          {log?.deliveries.map((delivery) => <DeliveryRow key={delivery.id} delivery={delivery} />)}
        </ul>
      )}

      {log && log.total_pages > 1 && (
        <div className="pager">
          <Button
            variant="ghost"
            aria-label="Newer deliveries"
            disabled={log.page <= 1}
            onClick={() => setPage(log.page - 1)}
          >
            <ChevronLeft size={16} />
          </Button>
          <span>
            Page {log.page} of {log.total_pages}
          </span>
          <Button
            variant="ghost"
            aria-label="Older deliveries"
            disabled={log.page >= log.total_pages}
            onClick={() => setPage(log.page + 1)}
          >
            <ChevronRight size={16} />
          </Button>
        </div>
      )}
    </AdminPanel>
  );
}

function DeliveryRow({ delivery }: { delivery: Delivery }) {
  const problem = PROBLEM.has(delivery.status);
  const when = ageLabel(delivery.ended_at ?? delivery.created_at);
  const kind = EVENT_TYPES[delivery.event_type] ?? delivery.event_type;
  const attempts = `${delivery.attempts} ${delivery.attempts === 1 ? "attempt" : "attempts"}`;

  return (
    <li
      className={`delivery-row${problem ? " delivery-row-problem" : ""}`}
      // The error shows on hover; it stays in the row for screen readers too.
      title={delivery.last_error ?? undefined}
    >
      <div className="delivery-row-main">
        <strong>{delivery.subject}</strong>
        <span className="admin-muted">
          {kind} · {delivery.destination_label} · {attempts}
          {when && ` · ${delivery.ended_at ? "ended" : "queued"} ${when}`}
        </span>
        {problem && delivery.last_error && <span className="delivery-row-error">Error: {delivery.last_error}</span>}
      </div>
      <Pill tone={statusTone(delivery.status)}>{delivery.status}</Pill>
    </li>
  );
}
