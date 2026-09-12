import type { LineIntent } from "./api";

export const demoEventId = "nba-knicks-celtics-2026-04-11";

export const sportsbookOptions = ["Best", "FanDuel", "DraftKings", "BetMGM", "Caesars"];

export type MarketLine = LineIntent & {
  id: string;
  label: string;
  matchup: string;
  league: string;
  startsAt: string;
};

export const marketLines: MarketLine[] = [
  {
    id: "knicks-moneyline",
    event_id: demoEventId,
    market_type: "moneyline",
    selection: "knicks",
    target_price: 121,
    label: "Knicks Moneyline",
    matchup: "Knicks at Celtics",
    league: "NBA",
    startsAt: "Demo fixture"
  },
  {
    id: "celtics-moneyline",
    event_id: demoEventId,
    market_type: "moneyline",
    selection: "celtics",
    target_price: -140,
    label: "Celtics Moneyline",
    matchup: "Knicks at Celtics",
    league: "NBA",
    startsAt: "Demo fixture"
  },
  {
    id: "knicks-spread-55",
    event_id: demoEventId,
    market_type: "spread",
    selection: "knicks",
    line: 5.5,
    target_price: -108,
    label: "Knicks +5.5",
    matchup: "Knicks at Celtics",
    league: "NBA",
    startsAt: "Demo fixture"
  },
  {
    id: "over-2215",
    event_id: demoEventId,
    market_type: "total",
    selection: "over",
    line: 221.5,
    target_price: -105,
    label: "Over 221.5",
    matchup: "Knicks at Celtics",
    league: "NBA",
    startsAt: "Demo fixture"
  },
  {
    id: "under-2215",
    event_id: demoEventId,
    market_type: "total",
    selection: "under",
    line: 221.5,
    target_price: -105,
    label: "Under 221.5",
    matchup: "Knicks at Celtics",
    league: "NBA",
    startsAt: "Demo fixture"
  }
];

export function formatAmerican(price?: number | null) {
  if (price === null || price === undefined) return "--";
  return price > 0 ? `+${price}` : `${price}`;
}
