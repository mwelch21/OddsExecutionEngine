import { Bell, RefreshCcw } from "lucide-react";
import type { Recommendation } from "../lib/api";
import { formatAmerican, type MarketLine } from "../lib/fixtures";
import { Button, Pill } from "./primitives";

type Props = {
  lines: MarketLine[];
  recommendations: Record<string, Recommendation>;
  selectedBook: string;
  loading: boolean;
  onBookChange: (book: string) => void;
  onRefresh: () => void;
  onOpenWatch: (line: MarketLine) => void;
  books: string[];
};

export function LineBoard({
  lines,
  recommendations,
  selectedBook,
  loading,
  onBookChange,
  onRefresh,
  onOpenWatch,
  books
}: Props) {
  const matchupGroups = lines.reduce<Record<string, MarketLine[]>>((groups, line) => {
    groups[line.matchup] = [...(groups[line.matchup] ?? []), line];
    return groups;
  }, {});

  return (
    <section className="line-board">
      <div className="panel-heading">
        <div>
          <Pill tone="accent">Lines</Pill>
          <h2>Best available execution</h2>
          <p>Filter by sportsbook. Best shows current best line per market.</p>
        </div>
        <div className="board-actions">
          <div className="book-filter" aria-label="Sportsbook filter">
            {books.map((book) => (
              <button
                className={book === selectedBook ? "book-chip active" : "book-chip"}
                key={book}
                onClick={() => onBookChange(book)}
              >
                {book}
              </button>
            ))}
          </div>
          <Button onClick={onRefresh} disabled={loading}>
            <RefreshCcw size={16} />
            Refresh
          </Button>
        </div>
      </div>

      <div className="game-stack">
        {Object.entries(matchupGroups).map(([matchup, matchupLines]) => (
          <article className="game-card" key={matchup}>
            <div className="game-card-header">
              <div>
                <span className="league">{matchupLines[0]?.league}</span>
                <h3>{matchup}</h3>
                <small>{matchupLines[0]?.startsAt}</small>
              </div>
              <Button variant="ghost" title="Create watch" onClick={() => onOpenWatch(matchupLines[0])}>
                <Bell size={16} />
              </Button>
            </div>

            <div className="team-lines">
      <TeamLine
        label="Knicks"
        tone="accent"
        lines={[
          findLine(matchupLines, "knicks", "moneyline"),
          findLine(matchupLines, "knicks", "spread"),
          findLine(matchupLines, "over", "total")
        ]}
                recommendations={recommendations}
                selectedBook={selectedBook}
                onOpenWatch={onOpenWatch}
              />
              <div className="match-divider" />
      <TeamLine
        label="Celtics"
        tone="neutral"
        lines={[
          findLine(matchupLines, "celtics", "moneyline"),
          findLine(matchupLines, "celtics", "spread"),
          findLine(matchupLines, "under", "total")
        ]}
                recommendations={recommendations}
                selectedBook={selectedBook}
                onOpenWatch={onOpenWatch}
              />
            </div>
          </article>
        ))}
      </div>
    </section>
  );
}

function TeamLine({
  label,
  tone,
  lines,
  recommendations,
  selectedBook,
  onOpenWatch
}: {
  label: string;
  tone: "accent" | "neutral";
  lines: Array<MarketLine | undefined>;
  recommendations: Record<string, Recommendation>;
  selectedBook: string;
  onOpenWatch: (line: MarketLine) => void;
}) {
  return (
    <div className="team-row">
      <div className="team-identity">
        <div className={`team-avatar ${tone}`}>{label.slice(0, 2)}</div>
        <strong>{label}</strong>
      </div>
      <div className="bet-button-row">
        {lines.map((line, index) => (
          line ? (
            <BetButton
              key={line.id}
              line={line}
              recommendation={recommendations[line.id]}
              selectedBook={selectedBook}
              onOpenWatch={onOpenWatch}
            />
          ) : (
            <div className="bet-button bet-button-empty" key={`empty-${label}-${index}`} aria-hidden="true" />
          )
        ))}
      </div>
    </div>
  );
}

function BetButton({
  line,
  recommendation,
  selectedBook,
  onOpenWatch
}: {
  line: MarketLine;
  recommendation: Recommendation | undefined;
  selectedBook: string;
  onOpenWatch: (line: MarketLine) => void;
}) {
  const shownQuote =
    selectedBook === "Best"
      ? recommendation?.best_quote
      : recommendation?.ranked_quotes.find((quote) => quote.sportsbook === selectedBook) ?? null;
  const bookLabel = selectedBook === "Best" ? shownQuote?.sportsbook ?? "Best" : selectedBook;

  return (
    <button
      className="bet-button"
      onClick={() => onOpenWatch(line)}
    >
      <span className="bet-label">{getBetLabel(line)}</span>
      <span className="bet-price-line">
        {line.line !== undefined && <span className="bet-line">{formatLine(line)}</span>}
        <strong>{formatAmerican(shownQuote?.price)}</strong>
      </span>
      <span className="bet-book">{bookLabel}</span>
    </button>
  );
}

function findLine(lines: MarketLine[], selection: string, marketType: MarketLine["market_type"]) {
  return lines.find((line) => line.selection === selection && line.market_type === marketType);
}

function getBetLabel(line: MarketLine) {
  if (line.market_type === "moneyline") return "ML";
  if (line.market_type === "spread") return "Spread";
  return line.selection === "over" ? "Over" : "Under";
}

function formatLine(line: MarketLine) {
  if (line.market_type === "spread" && line.line !== undefined) {
    return line.line > 0 ? `+${line.line}` : `${line.line}`;
  }
  if (line.market_type === "total" && line.line !== undefined) {
    return `${line.line}`;
  }
  return "";
}
