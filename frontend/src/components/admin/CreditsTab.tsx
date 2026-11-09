import { RotateCw } from "lucide-react";
import { useEffect, useState } from "react";
import { getAutoRefresh, type AutoRefresh } from "../../lib/adminApi";
import { Button } from "../primitives";
import { CreditBurnPanel } from "./credits/CreditBurnPanel";
import { CreditMeterPanel } from "./credits/CreditMeterPanel";
import { QuotaHistoryPanel } from "./credits/QuotaHistoryPanel";

/**
 * What credits cost and where they go (#104): the meter, 30 days of balance and
 * this month's burn per sport. Stored reads only; read when the tab opens and on
 * Reload, never polled, so looking at credits never spends one.
 */
export function CreditsTab() {
  const [reloads, setReloads] = useState(0);
  const [status, setStatus] = useState<AutoRefresh | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    getAutoRefresh()
      .then((response) => {
        if (cancelled) return;
        setStatus(response);
        setError(null);
      })
      .catch((reason: unknown) => {
        if (!cancelled) setError(reason instanceof Error ? reason.message : "Unavailable");
      });
    return () => {
      cancelled = true;
    };
  }, [reloads]);

  const reload = (
    <Button variant="ghost" aria-label="Reload credits" onClick={() => setReloads((n) => n + 1)}>
      <RotateCw size={16} />
    </Button>
  );

  return (
    <div className="credits-tab">
      <CreditMeterPanel status={status} error={error} actions={reload} />
      <CreditBurnPanel reloads={reloads} />
      <QuotaHistoryPanel floor={status?.quota?.floor ?? null} reloads={reloads} />
    </div>
  );
}
