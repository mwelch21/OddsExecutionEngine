import { X } from "lucide-react";
import type { LineBoard, Opportunity } from "../lib/api";
import { ageLabel, formatAmerican, formatLine, marketLabel } from "../lib/format";
import { Button, Pill } from "./primitives";

type Props = {
  opportunity: Opportunity;
  board: LineBoard | null;
  onDismiss: () => void;
};

/**
 * The opportunity a notification pointed at, pinned above its event's board.
 *
 * Only a still-valid opportunity reaches this banner; an invalid one degrades to
 * a note in the hero strip instead, so nothing here reads as actionable when it
 * is not.
 */
export function OpportunityBanner({ opportunity, board, onDismiss }: Props) {
  const lineText = formatLine(opportunity);
  const selection =
    opportunity.market_type === "total"
      ? `${marketLabel(opportunity)} ${lineText}`
      : `${opportunity.selection} ${marketLabel(opportunity)}${lineText ? ` ${lineText}` : ""}`;
  const fillable = opportunity.matching_quotes.length;

  return (
    <section className="opportunity-banner" aria-label="Opportunity">
      <div>
        <Pill tone="good">Opportunity · fillable</Pill>
        <h2>
          {selection} {formatAmerican(opportunity.best_price)} @ {opportunity.best_sportsbook}
        </h2>
        <p>
          Target {formatAmerican(opportunity.target_price)} · {fillable}{" "}
          {fillable === 1 ? "book" : "books"} fillable · {bookQuoteAge(opportunity, board)} ·
          Valid now
        </p>
      </div>
      <Button variant="ghost" title="Dismiss" onClick={onDismiss}>
        <X size={16} />
      </Button>
    </section>
  );
}

/**
 * How long ago the best book last moved this line, read from the live board.
 *
 * A book that reports no line time says so rather than showing an age; the
 * board is the source because the opportunity stores no quote timestamp.
 */
function bookQuoteAge(opportunity: Opportunity, board: LineBoard | null) {
  const market = board?.markets.find(
    (candidate) =>
      candidate.market_type === opportunity.market_type &&
      candidate.selection === opportunity.selection &&
      candidate.line === opportunity.line
  );
  const quote = market?.quotes.find(
    (candidate) => candidate.sportsbook === opportunity.best_sportsbook
  );
  if (!quote) return "book no longer quoting";
  const age = quote.line_age_known ? ageLabel(quote.quoted_at) : null;
  return age ? `book quoted ${age}` : "book line age unknown";
}
