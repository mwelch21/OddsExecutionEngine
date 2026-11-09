import { useEffect, useState } from "react";
import { getCreditBurn, type CreditBurn, type UpstreamCallKind } from "../../../lib/adminApi";
import { EmptyState } from "../../primitives";
import { AdminPanel } from "../AdminPanel";

const KIND_LABEL: Record<UpstreamCallKind, string> = {
  sport: "Sport pulls",
  event: "Event pulls",
  balance_check: "Balance checks"
};

/**
 * This month's credits per sport and per call kind, from
 * `GET /api/v1/admin/credit-burn`. Counted per upstream call, so refreshes that
 * shared one call count once.
 */
export function CreditBurnPanel({ reloads }: { reloads: number }) {
  const [burn, setBurn] = useState<CreditBurn | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    getCreditBurn()
      .then((response) => {
        if (cancelled) return;
        setBurn(response);
        setError(null);
      })
      .catch((reason: unknown) => {
        if (!cancelled) setError(reason instanceof Error ? reason.message : "Unavailable");
      });
    return () => {
      cancelled = true;
    };
  }, [reloads]);

  const top = burn ? Math.max(...burn.by_sport.map((s) => s.credits), 1) : 1;

  return (
    <AdminPanel title={burn ? `Burn, ${monthLabel(burn.starts_at)}` : "Burn this month"}>
      {error && <p className="admin-warn">{error}</p>}
      {!burn && !error && <p className="admin-muted">Loading…</p>}
      {burn && burn.total_calls === 0 && (
        <EmptyState>No upstream call this month yet. Spend per sport shows here.</EmptyState>
      )}
      {burn && burn.total_calls > 0 && (
        <>
          <p className="credit-burn-total">
            <strong>{burn.total_credits}</strong>
            <span className="admin-muted">
              {" "}
              credits over {burn.total_calls} call{burn.total_calls === 1 ? "" : "s"}
            </span>
          </p>
          {burn.by_sport.length > 0 && (
            <ul className="credit-burn-list" aria-label="Credits per sport">
              {burn.by_sport.map((sport) => (
                <li key={sport.sport} className="credit-burn-row">
                  <span className="credit-burn-name">{sport.sport}</span>
                  <span className="credit-burn-bar">
                    <span style={{ width: `${(sport.credits / top) * 100}%` }} />
                  </span>
                  <span className="credit-burn-value">
                    {sport.credits}
                    <span className="admin-muted"> · {sport.calls}×</span>
                  </span>
                </li>
              ))}
            </ul>
          )}
          <p className="admin-muted credit-burn-kinds">
            {burn.by_kind
              .map((kind) => `${KIND_LABEL[kind.kind]}: ${kind.credits} (${kind.calls}×)`)
              .join(" · ")}
          </p>
        </>
      )}
    </AdminPanel>
  );
}

function monthLabel(startsAt: string) {
  return new Date(startsAt).toLocaleDateString(undefined, {
    month: "long",
    year: "numeric",
    timeZone: "UTC"
  });
}
