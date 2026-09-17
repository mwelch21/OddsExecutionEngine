import type { EventQuoteFreshness, EventSummary, LineBoardMarket } from "./api";

export function formatAmerican(price?: number | null) {
  if (price === null || price === undefined) return "--";
  return price > 0 ? `+${price}` : `${price}`;
}

export function formatLine(market: Pick<LineBoardMarket, "market_type" | "line">) {
  if (market.line === null || market.line === undefined) return "";
  if (market.market_type === "spread") {
    return market.line > 0 ? `+${market.line}` : `${market.line}`;
  }
  return `${market.line}`;
}

export function marketLabel(market: Pick<LineBoardMarket, "market_type" | "selection">) {
  if (market.market_type === "moneyline") return "ML";
  if (market.market_type === "spread") return "Spread";
  return market.selection === "over" ? "Over" : "Under";
}

/** "Away at Home" when both sides are known, falling back to whatever we have. */
export function matchupLabel(event: Pick<EventSummary, "participants" | "id">) {
  const home = event.participants.find((p) => p.side === "home");
  const away = event.participants.find((p) => p.side === "away");
  if (away && home) return `${away.name} at ${home.name}`;
  const names = event.participants.map((p) => p.name);
  return names.length > 0 ? names.join(" vs ") : event.id;
}

export function formatStart(startsAt: string | null) {
  if (!startsAt) return "Start time unknown";
  const parsed = new Date(startsAt);
  if (Number.isNaN(parsed.getTime())) return "Start time unknown";
  return parsed.toLocaleString(undefined, {
    weekday: "short",
    month: "short",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit"
  });
}

/**
 * Age of a timestamp, or null when there is no timestamp to age.
 *
 * Returning null rather than "0s" matters: a null clock means we have never
 * pulled, or the book reports no line-movement time. Rendering that as zero
 * would read as freshly moved, which is the opposite of the truth.
 */
export function ageLabel(timestamp: string | null, now: number = Date.now()) {
  if (!timestamp) return null;
  const parsed = new Date(timestamp);
  if (Number.isNaN(parsed.getTime())) return null;
  const seconds = Math.max(0, Math.round((now - parsed.getTime()) / 1000));
  if (seconds < 60) return `${seconds}s ago`;
  const minutes = Math.floor(seconds / 60);
  if (minutes < 60) return `${minutes}m ago`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours}h ago`;
  return `${Math.floor(hours / 24)}d ago`;
}

export type FreshnessSummary = {
  pulled: string;
  lines: string;
  tone: "good" | "warn" | "neutral";
  unknownNote: string | null;
};

/**
 * Both clocks as display strings, kept apart on purpose.
 *
 * An event pulled ten seconds ago whose books last moved three days back is
 * three days stale, and the UI has to be able to say so.
 */
export function summarizeFreshness(
  freshness: EventQuoteFreshness,
  now: number = Date.now()
): FreshnessSummary {
  const pulledAge = ageLabel(freshness.last_ingested_at, now);
  const lineAge = ageLabel(freshness.oldest_line_quoted_at, now);

  const unknownNote =
    freshness.books_with_unknown_line_age > 0
      ? `${freshness.books_with_unknown_line_age} of ${freshness.book_count} books report no line time`
      : null;

  if (freshness.quote_count === 0) {
    return {
      pulled: "Never pulled",
      lines: "No lines stored",
      tone: "warn",
      unknownNote: null
    };
  }

  return {
    pulled: pulledAge ? `Pulled ${pulledAge}` : "Pull time unknown",
    lines: lineAge ? `Oldest line ${lineAge}` : "Line age unknown",
    tone: pulledAge === null ? "neutral" : "good",
    unknownNote
  };
}
