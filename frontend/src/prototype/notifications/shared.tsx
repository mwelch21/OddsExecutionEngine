/** PROTOTYPE ONLY: tiny bits the variants share. Layout is never shared. */
import { formatAmerican } from "../../lib/format";
import type { SimState } from "./sim";

export function ApiTag({ children }: { children: string }) {
  return <code className="proto-api">{children}</code>;
}

export function CreditMeter({ credits }: { credits: SimState["credits"] }) {
  const plan = credits.remaining + credits.used || 1;
  const pct = Math.round((credits.remaining / plan) * 100);
  const floorPct = Math.round((credits.floor / plan) * 100);
  const tone = credits.remaining === 0 ? "danger" : credits.remaining < credits.floor ? "warn" : "good";
  return (
    <div className="proto-meter" title={`${credits.remaining} of ${plan} credits left`}>
      <div className={`proto-meter-fill proto-${tone}`} style={{ width: `${pct}%` }} />
      <div className="proto-meter-floor" style={{ left: `${floorPct}%` }} />
    </div>
  );
}

export function price(p: number) {
  return formatAmerican(p);
}

export function ago(iso: string | null) {
  if (!iso) return "never";
  const s = Math.max(0, Math.round((Date.now() - new Date(iso).getTime()) / 1000));
  if (s < 60) return `${s}s ago`;
  if (s < 3600) return `${Math.round(s / 60)}m ago`;
  if (s < 86400) return `${Math.round(s / 3600)}h ago`;
  return `${Math.round(s / 86400)}d ago`;
}

export function statusLabel(state: SimState) {
  const ar = state.autoRefresh;
  if (!ar.enabled) return "Off: manual refresh only";
  if (ar.status === "paused_out_of_credits") return "On · paused: out of credits until the 1st";
  return `On · every ${ar.intervalMinutes} min · ${ar.sports.length} watched sports`;
}
