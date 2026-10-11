/**
 * PROTOTYPE ONLY: in-memory stand-in for the notification layer's API.
 * Nothing here persists or calls the backend; every mutation names the public
 * endpoint it represents (ADR-014/015/016, ticket #59) so the UI can be judged
 * against the real contract.
 */
import { useReducer } from "react";
import type { LineBoard, LineBoardMarket } from "../../lib/api";

export type AutoRefreshStatus = "off" | "running" | "paused_out_of_credits";

export type Destination = {
  id: string;
  label: string;
  status: "active" | "gone" | "user_removed";
  lastDeliveredAt: string | null;
};

export type Opportunity = {
  id: string;
  eventLabel: string;
  startsAt: string | null;
  marketLabel: string;
  selection: string;
  line: string;
  targetPrice: number;
  best: { sportsbook: string; price: number; quotedAt: string | null };
  matching: { sportsbook: string; price: number }[];
  validMinutesLeft: number;
};

export type AppNotice = { id: string; kind: "opportunity" | "quota" | "test"; text: string; at: string };

export type SimState = {
  autoRefresh: {
    enabled: boolean;
    status: AutoRefreshStatus;
    intervalMinutes: number;
    lastTick: { at: string; outcome: string } | null;
    sports: { key: string; watches: number; lastRefreshedMinutesAgo: number }[];
  };
  credits: { remaining: number; used: number; floor: number };
  installedToHomeScreen: boolean;
  permission: "default" | "granted" | "denied";
  destinations: Destination[];
  onboardingStep: 0 | 1 | 2 | 3;
  tapped: Opportunity | null;
  notices: AppNotice[];
  apiLog: string[];
};

type Action =
  | { type: "toggleAutoRefresh" }
  | { type: "setInterval"; minutes: number }
  | { type: "quotaDropsBelowFloor" }
  | { type: "outOfCredits" }
  | { type: "creditsReset" }
  | { type: "install" }
  | { type: "grantPermission" }
  | { type: "sendTest"; destinationId: string }
  | { type: "removeDestination"; id: string }
  | { type: "destinationGone"; id: string }
  | { type: "setOnboardingStep"; step: SimState["onboardingStep"] }
  | { type: "tapOpportunity"; opportunity: Opportunity }
  | { type: "closeOpportunity" }
  | { type: "reset" };

const now = () => new Date().toISOString();
const PLAN = 500;

export const initialState: SimState = {
  autoRefresh: {
    enabled: false,
    status: "off",
    intervalMinutes: 5,
    lastTick: null,
    sports: [
      { key: "basketball_nba", watches: 2, lastRefreshedMinutesAgo: 3 },
      { key: "americanfootball_nfl", watches: 1, lastRefreshedMinutesAgo: 11 }
    ]
  },
  credits: { remaining: 212, used: PLAN - 212, floor: 50 },
  installedToHomeScreen: false,
  permission: "default",
  destinations: [
    { id: "d-mac", label: "MacBook · Chrome", status: "active", lastDeliveredAt: now() }
  ],
  onboardingStep: 0,
  tapped: null,
  notices: [],
  apiLog: []
};

function log(state: SimState, call: string): SimState {
  return { ...state, apiLog: [`${new Date().toLocaleTimeString()}  ${call}`, ...state.apiLog].slice(0, 8) };
}

function reducer(state: SimState, action: Action): SimState {
  switch (action.type) {
    case "toggleAutoRefresh": {
      const enabled = !state.autoRefresh.enabled;
      const status: AutoRefreshStatus = !enabled
        ? "off"
        : state.credits.remaining === 0
          ? "paused_out_of_credits"
          : "running";
      return log(
        {
          ...state,
          autoRefresh: {
            ...state.autoRefresh,
            enabled,
            status,
            lastTick: enabled ? { at: now(), outcome: "refreshed basketball_nba (3 credits)" } : state.autoRefresh.lastTick
          }
        },
        `PUT /auto-refresh {enabled: ${enabled}}`
      );
    }
    case "setInterval":
      return log(
        { ...state, autoRefresh: { ...state.autoRefresh, intervalMinutes: action.minutes } },
        `PUT /auto-refresh {interval_minutes: ${action.minutes}}`
      );
    case "quotaDropsBelowFloor":
      return {
        ...state,
        credits: { ...state.credits, remaining: state.credits.floor - 3, used: PLAN - state.credits.floor + 3 },
        notices: [
          { id: crypto.randomUUID(), kind: "quota", text: `Credits low: ${state.credits.floor - 3} left (floor ${state.credits.floor})`, at: now() },
          ...state.notices
        ],
        apiLog: [`(public event) oddsengine.quota.warning.v1`, ...state.apiLog].slice(0, 8)
      };
    case "outOfCredits":
      return {
        ...state,
        credits: { ...state.credits, remaining: 0, used: PLAN },
        autoRefresh: {
          ...state.autoRefresh,
          status: state.autoRefresh.enabled ? "paused_out_of_credits" : "off",
          lastTick: { at: now(), outcome: "OUT_OF_USAGE_CREDITS: paused until reset" }
        }
      };
    case "creditsReset":
      return {
        ...state,
        credits: { ...state.credits, remaining: PLAN, used: 0 },
        autoRefresh: { ...state.autoRefresh, status: state.autoRefresh.enabled ? "running" : "off" }
      };
    case "install":
      return { ...state, installedToHomeScreen: true, onboardingStep: Math.max(state.onboardingStep, 1) as SimState["onboardingStep"] };
    case "grantPermission": {
      const iphone: Destination = { id: "d-iphone", label: "iPhone · Safari", status: "active", lastDeliveredAt: null };
      const others = state.destinations.filter((d) => d.id !== "d-iphone");
      return log(
        { ...state, permission: "granted", destinations: [iphone, ...others], onboardingStep: 2 },
        "POST /destinations/web-push {endpoint, keys, label}"
      );
    }
    case "sendTest":
      return log(
        {
          ...state,
          onboardingStep: state.onboardingStep === 2 ? 3 : state.onboardingStep,
          destinations: state.destinations.map((d) => (d.id === action.destinationId ? { ...d, lastDeliveredAt: now() } : d)),
          notices: [{ id: crypto.randomUUID(), kind: "test", text: "Test notification delivered", at: now() }, ...state.notices]
        },
        `POST /destinations/${action.destinationId}/test`
      );
    case "removeDestination":
      return log(
        { ...state, destinations: state.destinations.map((d) => (d.id === action.id ? { ...d, status: "user_removed" } : d)) },
        `DELETE /destinations/${action.id}`
      );
    case "destinationGone":
      return {
        ...state,
        destinations: state.destinations.map((d) => (d.id === action.id ? { ...d, status: "gone" } : d)),
        apiLog: [`(notifier) 410 from push service → ${action.id} gone`, ...state.apiLog].slice(0, 8)
      };
    case "setOnboardingStep":
      return { ...state, onboardingStep: action.step };
    case "tapOpportunity":
      return log(
        {
          ...state,
          tapped: action.opportunity,
          notices: [
            { id: action.opportunity.id, kind: "opportunity", text: `${action.opportunity.selection} ${action.opportunity.marketLabel} fillable`, at: now() },
            ...state.notices
          ]
        },
        `GET /opportunities/${action.opportunity.id}`
      );
    case "closeOpportunity":
      return { ...state, tapped: null };
    case "reset":
      return initialState;
  }
}

export function useSim() {
  return useReducer(reducer, initialState);
}

export type Dispatch = ReturnType<typeof useSim>[1];

/** Build a believable opportunity from a real board when one is loaded. */
export function opportunityFrom(board: LineBoard | null): Opportunity {
  const market: LineBoardMarket | undefined = board?.markets.find((m) => m.best_price !== null && m.quotes.length > 1);
  if (!board || !market || market.best_price === null) {
    return {
      id: "opp-demo",
      eventLabel: "New York Knicks at Boston Celtics",
      startsAt: new Date(Date.now() + 3 * 3600_000).toISOString(),
      marketLabel: "ML",
      selection: "New York Knicks",
      line: "",
      targetPrice: 120,
      best: { sportsbook: "draftkings", price: 125, quotedAt: new Date(Date.now() - 90_000).toISOString() },
      matching: [
        { sportsbook: "draftkings", price: 125 },
        { sportsbook: "fanduel", price: 122 },
        { sportsbook: "betmgm", price: 120 }
      ],
      validMinutesLeft: 712
    };
  }
  const target = market.best_price - 5;
  const home = board.event.participants.find((p) => p.side === "home")?.name;
  const away = board.event.participants.find((p) => p.side === "away")?.name;
  return {
    id: "opp-live-data",
    eventLabel: away && home ? `${away} at ${home}` : board.event.id,
    startsAt: board.event.starts_at,
    marketLabel: market.market_type === "moneyline" ? "ML" : market.market_type === "spread" ? "Spread" : market.selection,
    selection: market.selection,
    line: market.line === null ? "" : String(market.line),
    targetPrice: target,
    best: {
      sportsbook: market.best_sportsbook ?? "?",
      price: market.best_price,
      quotedAt: market.quotes[0]?.quoted_at ?? null
    },
    matching: market.quotes.filter((q) => q.price >= target).map((q) => ({ sportsbook: q.sportsbook, price: q.price })),
    validMinutesLeft: 712
  };
}
