import { ArrowLeft, Bell, Crown } from "lucide-react";
import type { LineBoard as LineBoardData, LineBoardMarket } from "../lib/api";
import {
  ageLabel,
  formatAmerican,
  formatLine,
  formatStart,
  marketLabel,
  summarizeFreshness
} from "../lib/format";
import { Button, EmptyState, Pill } from "./primitives";

type Props = {
  board: LineBoardData | null;
  loading: boolean;
  onBack: () => void;
  onOpenWatch: (market: LineBoardMarket) => void;
};

const MARKET_ORDER: Record<string, number> = { moneyline: 0, spread: 1, total: 2 };

export function LineBoard({ board, loading, onBack, onOpenWatch }: Props) {
  if (loading) {
    return (
      <section className="line-board">
        <div className="loading-note">Loading line board</div>
      </section>
    );
  }

  if (!board) {
    return (
      <section className="line-board">
        <EmptyState>Select an event to see its board.</EmptyState>
      </section>
    );
  }

  const freshness = summarizeFreshness(board.event.quotes);
  const groups = groupByMarket(board.markets);

  return (
    <section className="line-board">
      <div className="panel-heading">
        <div>
          <Button variant="ghost" className="back-button" onClick={onBack}>
            <ArrowLeft size={16} />
            All events
          </Button>
          <p>
            {board.event.league ?? board.event.sport ?? "Unknown league"} ·{" "}
            {formatStart(board.event.starts_at)}
          </p>
        </div>
        <div className="board-freshness">
          <Pill tone={freshness.tone === "warn" ? "warn" : "good"}>{freshness.pulled}</Pill>
          <small>{freshness.lines}</small>
          {freshness.unknownNote && (
            <small className="unknown-note">{freshness.unknownNote}</small>
          )}
        </div>
      </div>

      {board.markets.length === 0 ? (
        <EmptyState>
          No lines stored for this event. Refresh its sport to pull them.
        </EmptyState>
      ) : (
        <div className="market-stack">
          {groups.map(([marketType, markets]) => (
            <article className="market-group" key={marketType}>
              <h3>{marketTypeHeading(marketType)}</h3>
              {markets.map((market) => (
                <MarketRow
                  key={`${market.market_type}-${market.selection}-${market.line ?? "na"}`}
                  market={market}
                  onOpenWatch={onOpenWatch}
                />
              ))}
            </article>
          ))}
        </div>
      )}
    </section>
  );
}

function MarketRow({
  market,
  onOpenWatch
}: {
  market: LineBoardMarket;
  onOpenWatch: (market: LineBoardMarket) => void;
}) {
  const lineText = formatLine(market);

  return (
    <div className="market-row">
      <div className="market-identity">
        <span className="bet-label">{marketLabel(market)}</span>
        <strong>{market.selection}</strong>
        {lineText && <span className="bet-line">{lineText}</span>}
      </div>

      <div className="quote-strip">
        {market.quotes.map((quote) => {
          // The backend names the best book rather than leaving the client to
          // sort: at an identical price only the engine's tie-break decides,
          // and a watch would fire on the engine's pick, not ours.
          const isBest = quote.sportsbook === market.best_sportsbook;
          const age = ageLabel(quote.quoted_at);
          return (
            <div
              className={isBest ? "quote-chip quote-chip-best" : "quote-chip"}
              key={quote.sportsbook}
            >
              <span className="quote-book">
                {isBest && <Crown size={12} />}
                {quote.sportsbook}
              </span>
              <strong>{formatAmerican(quote.price)}</strong>
              <small>{quote.line_age_known ? age : "line age unknown"}</small>
            </div>
          );
        })}
      </div>

      <Button variant="ghost" title="Create watch" onClick={() => onOpenWatch(market)}>
        <Bell size={16} />
      </Button>
    </div>
  );
}

function groupByMarket(markets: LineBoardMarket[]): Array<[string, LineBoardMarket[]]> {
  const groups = new Map<string, LineBoardMarket[]>();
  for (const market of markets) {
    groups.set(market.market_type, [...(groups.get(market.market_type) ?? []), market]);
  }
  return [...groups.entries()].sort(
    ([a], [b]) => (MARKET_ORDER[a] ?? 99) - (MARKET_ORDER[b] ?? 99)
  );
}

function marketTypeHeading(marketType: string) {
  if (marketType === "moneyline") return "Moneyline";
  if (marketType === "spread") return "Spread";
  if (marketType === "total") return "Total";
  return marketType;
}
