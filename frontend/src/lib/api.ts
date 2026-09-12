export type MarketType = "moneyline" | "spread" | "total";

export type LineIntent = {
  event_id: string;
  market_type: MarketType;
  selection: string;
  line?: number;
  target_price: number;
};

export type Quote = {
  sportsbook: string;
  selection: string;
  price: number;
  line: number | null;
};

export type Recommendation = {
  request: {
    event_id: string;
    market_type: MarketType;
    selection: string;
    line: number | null;
    target_price: number;
  };
  fillable: boolean;
  best_quote: Quote | null;
  ranked_quotes: Quote[];
  nearest_miss: Quote | null;
  matched_quote_count: number;
};

export type WatchIntent = {
  id: string;
  event_id: string;
  market_type: MarketType;
  selection: string;
  target_price: number;
  line: number | null;
  status: "active" | "triggered" | "cancelled" | "expired";
  created_at: string | null;
};

export type WatchList = {
  watch_intents: WatchIntent[];
};

export async function refreshQuotes(eventId: string) {
  return request<{ event_id: string; ingested_quote_count: number }>("/ingestion/quotes/refresh", {
    method: "POST",
    body: JSON.stringify({ event_id: eventId })
  });
}

export async function getRecommendation(intent: LineIntent) {
  return request<Recommendation>("/execution/recommendation", {
    method: "POST",
    body: JSON.stringify(intent)
  });
}

export async function createWatch(intent: LineIntent) {
  return request<WatchIntent & { opportunity?: unknown }>("/watch-intents", {
    method: "POST",
    body: JSON.stringify(intent)
  });
}

export async function listWatches(eventId: string) {
  return request<WatchList>(`/watch-intents?event_id=${encodeURIComponent(eventId)}`);
}

export async function cancelWatch(id: string) {
  const response = await fetch(`/watch-intents/${encodeURIComponent(id)}`, {
    method: "DELETE"
  });
  if (!response.ok) {
    throw new Error(`DELETE /watch-intents/${id} failed: ${response.status}`);
  }
}

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const response = await fetch(path, {
    headers: { "Content-Type": "application/json", ...(init.headers ?? {}) },
    ...init
  });
  if (!response.ok) {
    const body = await response.text();
    throw new Error(`${path} failed: ${response.status} ${body}`);
  }
  return response.json() as Promise<T>;
}
