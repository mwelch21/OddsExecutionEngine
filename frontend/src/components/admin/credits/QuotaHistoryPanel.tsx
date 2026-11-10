import { useEffect, useState } from "react";
import { getQuotaHistory, type QuotaHistory } from "../../../lib/adminApi";
import { EmptyState } from "../../primitives";
import { AdminPanel } from "../AdminPanel";

const DAYS = 30;
const HOUR_MS = 3_600_000;

/**
 * Remaining credits over the last 30 days: the last balance seen in each hour,
 * from `GET /api/v1/admin/quota-history`. The balance only changes on an upstream
 * call, so the line holds flat between points (a step line).
 */
export function QuotaHistoryPanel({ floor, reloads }: { floor: number | null; reloads: number }) {
  const [history, setHistory] = useState<QuotaHistory | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    getQuotaHistory(DAYS)
      .then((response) => {
        if (cancelled) return;
        setHistory(response);
        setError(null);
      })
      .catch((reason: unknown) => {
        if (!cancelled) setError(reason instanceof Error ? reason.message : "Unavailable");
      });
    return () => {
      cancelled = true;
    };
  }, [reloads]);

  return (
    <AdminPanel title={`Balance, last ${DAYS} days`}>
      {error && <p className="admin-warn">{error}</p>}
      {!history && !error && <p className="admin-muted">Loading…</p>}
      {history && history.points.length === 0 && (
        <EmptyState>No balance observed in the last {DAYS} days.</EmptyState>
      )}
      {history && history.points.length > 0 && (
        <HistoryChart points={history.points} floor={floor} />
      )}
    </AdminPanel>
  );
}

function HistoryChart({
  points,
  floor
}: {
  points: QuotaHistory["points"];
  floor: number | null;
}) {
  const end = Math.floor(Date.now() / HOUR_MS) * HOUR_MS + HOUR_MS;
  const start = end - DAYS * 24 * HOUR_MS;
  const top = Math.max(...points.map((p) => p.remaining), floor ?? 0, 1);
  // Plot in a 0-100 box stretched to the frame; strokes do not scale, and every
  // label is HTML, so text stays its own size at any width.
  const x = (t: number) => ((t - start) / (end - start)) * 100;
  const y = (v: number) => (1 - v / top) * 100;

  // Step line: hold each balance until the next hour that has a call, then to now.
  let path = "";
  points.forEach((point, index) => {
    const px = x(new Date(point.hour).getTime());
    const py = y(point.remaining);
    path += index === 0 ? `M${px},${py}` : `H${px}V${py}`;
  });
  path += "H100";

  const last = points[points.length - 1];
  const ticks = [top, Math.round(top / 2), 0];

  return (
    <figure className="credit-history">
      <div className="credit-history-plot">
        <div className="credit-history-ticks admin-muted" aria-hidden="true">
          {ticks.map((tick) => (
            <span key={tick} style={{ top: `${y(tick)}%` }}>
              {tick}
            </span>
          ))}
        </div>
        <svg
          viewBox="0 0 100 100"
          preserveAspectRatio="none"
          role="img"
          aria-label={`Remaining credits over ${DAYS} days; now ${last.remaining}`}
        >
          {ticks.map((tick) => (
            <line key={tick} className="credit-history-grid" x1={0} x2={100} y1={y(tick)} y2={y(tick)} />
          ))}
          {floor !== null && (
            <line className="credit-history-floor" x1={0} x2={100} y1={y(floor)} y2={y(floor)} />
          )}
          <path className="credit-history-line" d={path} />
        </svg>
      </div>
      <div className="credit-history-xaxis admin-muted" aria-hidden="true">
        <span>{DAYS} days ago</span>
        <span>now</span>
      </div>
      <figcaption className="admin-muted">
        {points.length} hour{points.length === 1 ? "" : "s"} with a call · now {last.remaining} left
        {floor !== null && ` · dashed line is the floor (${floor})`}
      </figcaption>
    </figure>
  );
}
