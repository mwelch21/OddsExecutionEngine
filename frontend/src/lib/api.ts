export type MarketType = "moneyline" | "spread" | "total";

export type LineIntent = {
  event_id: string;
  market_type: MarketType;
  selection: string;
  line?: number | null;
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

export type SupportedSport = {
  key: string;
  sport: string;
  league: string | null;
};

export type EventParticipant = {
  name: string;
  role: string;
  side: string | null;
};

/**
 * Two clocks, deliberately never collapsed into one.
 *
 * `last_ingested_at` is when we pulled. `oldest_line_quoted_at` is the oldest
 * line among the books that report one. Nulls mean "no such fact yet" — an
 * unrefreshed event, or books exposing no line-movement time — and must never
 * be rendered as zero age.
 */
export type EventQuoteFreshness = {
  quote_count: number;
  book_count: number;
  last_ingested_at: string | null;
  oldest_line_quoted_at: string | null;
  books_with_unknown_line_age: number;
};

export type EventSummary = {
  id: string;
  sport: string | null;
  league: string | null;
  status: string;
  starts_at: string | null;
  participants: EventParticipant[];
  quotes: EventQuoteFreshness;
};

export type EventPage = {
  events: EventSummary[];
  page: number;
  page_size: number;
  total_events: number;
  total_pages: number;
};

export type LineBoardQuote = {
  sportsbook: string;
  price: number;
  quoted_at: string | null;
  ingested_at: string | null;
  line_age_known: boolean;
};

export type LineBoardMarket = {
  market_type: MarketType;
  selection: string;
  line: number | null;
  best_sportsbook: string | null;
  best_price: number | null;
  quotes: LineBoardQuote[];
};

export type LineBoard = {
  event: EventSummary;
  markets: LineBoardMarket[];
};

export type SportRefreshResult = {
  sport: string;
  events_refreshed: number;
};

export type EventQuery = {
  league?: string | null;
  sport?: string | null;
  includeStarted?: boolean;
  page?: number;
  pageSize?: number;
};

/** Free: served from the database, never touching the upstream provider. */
export async function listEvents(query: EventQuery = {}) {
  const params = new URLSearchParams();
  if (query.league) params.set("league", query.league);
  if (query.sport) params.set("sport", query.sport);
  if (query.includeStarted) params.set("include_started", "true");
  params.set("page", String(query.page ?? 1));
  params.set("page_size", String(query.pageSize ?? 25));
  return request<EventPage>(`/events?${params.toString()}`);
}

/** Free: the stored board, ranked best-first by the backend. */
export async function getLineBoard(eventId: string) {
  return request<LineBoard>(`/events/${encodeURIComponent(eventId)}/quotes`);
}

export async function listSports() {
  return request<{ sports: SupportedSport[] }>("/sports");
}

/**
 * The only call in this client that spends upstream quota.
 *
 * Billed in credits, not requests: [markets] x [regions] per call. Callers are
 * expected to gate it behind an explicit user action.
 */
export async function refreshSport(sport: string) {
  return request<SportRefreshResult>("/ingestion/quotes/refresh-sport", {
    method: "POST",
    body: JSON.stringify({ sport })
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
