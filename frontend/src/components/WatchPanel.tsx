import { Bell, Trash2 } from "lucide-react";
import type { WatchIntent } from "../lib/api";
import { formatAmerican } from "../lib/fixtures";
import { Button, EmptyState, Panel, Pill } from "./primitives";

type Props = {
  watches: WatchIntent[];
  onCancel: (id: string) => void;
};

export function WatchPanel({ watches, onCancel }: Props) {
  return (
    <Panel>
      <div className="panel-heading compact">
        <div>
          <Pill tone="accent">Watches</Pill>
          <h2>Active watch intents</h2>
          <p>Backend owns terminal status and opportunity creation.</p>
        </div>
      </div>

      {watches.length === 0 ? (
        <EmptyState>
          <Bell size={22} />
          No watches yet.
        </EmptyState>
      ) : (
        <div className="watch-list">
          {watches.map((watch) => (
            <article className="watch-card" key={watch.id}>
              <div>
                <span className="league">{watch.market_type}</span>
                <strong>
                  {watch.selection}
                  {watch.line !== null ? ` ${watch.line}` : ""}
                </strong>
                <small>Target {formatAmerican(watch.target_price)}</small>
              </div>
              <Pill tone={watch.status === "active" ? "accent" : "good"}>{watch.status}</Pill>
              <Button variant="ghost" onClick={() => onCancel(watch.id)} title="Cancel watch">
                <Trash2 size={16} />
              </Button>
            </article>
          ))}
        </div>
      )}
    </Panel>
  );
}
