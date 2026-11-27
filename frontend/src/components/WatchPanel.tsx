import { Bell, Trash2 } from "lucide-react";
import type { WatchIntent } from "../lib/api";
import { expiredReasonLabel, formatAmerican, windowLabel } from "../lib/format";
import { Button, CollapseToggle, EmptyState, Panel, Pill, useCollapsed } from "./primitives";

type Props = {
  watches: WatchIntent[];
  /** Expired watches on this event, each shown with why (ADR-017). */
  expired: WatchIntent[];
  onCancel: (id: string) => void;
};

export function WatchPanel({ watches, expired, onCancel }: Props) {
  const [collapsed, toggle] = useCollapsed("watches");
  return (
    <Panel>
      <div className="panel-heading compact">
        <div>
          <Pill tone="accent">Watches</Pill>
          <div className="section-title">
            <h2>Active watch intents</h2>
            <CollapseToggle collapsed={collapsed} onToggle={toggle} label="watch intents" />
          </div>
          <p>Backend owns terminal status and opportunity creation.</p>
        </div>
      </div>

      {collapsed ? null : (
        <>
          {watches.length === 0 ? (
            <EmptyState>
              <Bell size={22} />
              No watches yet.
            </EmptyState>
          ) : (
            <div className="watch-list">
              {watches.map((watch) => (
                <article className="watch-card" key={watch.id}>
                  <WatchSummary watch={watch} />
                  <Pill tone={watch.status === "active" ? "accent" : "good"}>{watch.status}</Pill>
                  <Button variant="ghost" onClick={() => onCancel(watch.id)} title="Cancel watch">
                    <Trash2 size={16} />
                  </Button>
                </article>
              ))}
            </div>
          )}
          {expired.length > 0 && (
            <div className="watch-list watch-list-expired">
              <h3>Expired</h3>
              {expired.map((watch) => (
                <article className="watch-card watch-card-expired" key={watch.id}>
                  <WatchSummary watch={watch} />
                  <Pill tone="warn">{expiredReasonLabel(watch.expired_reason)}</Pill>
                </article>
              ))}
            </div>
          )}
        </>
      )}
    </Panel>
  );
}

function WatchSummary({ watch }: { watch: WatchIntent }) {
  return (
    <div>
      <span className="league">
        {watch.market_type} · {windowLabel(watch.window)}
      </span>
      <strong>
        {watch.selection}
        {watch.line !== null ? ` ${watch.line}` : ""}
      </strong>
      <small>Target {formatAmerican(watch.target_price)}</small>
    </div>
  );
}
