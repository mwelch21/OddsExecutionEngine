# OddsExecutionEngine — Architecture: Stages 5-6

## System Overview

Stages 5-6 extend the existing quote ingestion + recommendation pipeline (Stages 0-4) with:

- **Watch Intents** — persistent price alerts: "notify me when Knicks moneyline hits +120"
- **Opportunity Detection** — automatic matching of watch intents against live quotes
- **The Odds API Integration** — live sportsbook data for NHL, MLB, NBA, NFL
- **Flexible Event Schema** — `event_participants` table supporting team sports, individual sports, and player props

All computation is performed by pure, deterministic engines (zero I/O). All persistence uses the Unit of Work pattern with staged domain events committed atomically with data.

---

## Data Flows

### Flow A — Sport-Level Quote Refresh (Stage 6 primary entry point)

```
POST /ingestion/quotes/refresh-sport { sport: "icehockey_nhl" }
  |
  v
TheOddsApiProvider._fetch_sport_odds(sport)
  |  HTTP GET https://api.the-odds-api.com/v4/sports/{sport}/odds
  |  Params: apiKey, regions (us), markets (h2h,spreads,totals), oddsFormat=american
  |  Returns: list of event JSON objects with nested bookmakers/markets/outcomes
  |
  v
Per event in API response:
  |
  |-- _cache_event(event, sport_key)
  |     Parse sport/league from API key:
  |       "icehockey_nhl" -> sport="ice_hockey", league="NHL"
  |       "basketball_nba" -> sport="basketball", league="NBA"
  |     Extract participants:
  |       home_team -> EventParticipant(role="team", side="home", sort_order=1)
  |       away_team -> EventParticipant(role="team", side="away", sort_order=2)
  |     Build EventInfo with commence_time, sport, league, participants
  |
  |-- _map_event_to_quotes(event)
  |     Per bookmaker (draftkings, fanduel, betmgm, ...):
  |       Per market:
  |         h2h      -> MarketType.MONEYLINE (line forced to None)
  |         spreads  -> MarketType.SPREAD    (line from outcome.point)
  |         totals   -> MarketType.TOTAL     (selection must be "over"/"under")
  |       Per outcome:
  |         -> Quote(event_id, sportsbook, market_type, selection, price, line)
  |
  v
QuoteIngestionService.refresh_quotes(event_id, quotes_override, event_metadata)
  |
  |-- NormalizationEngine.normalize_quotes()                    [PURE ENGINE]
  |     Filter: only quotes matching target event_id
  |     Validate: moneyline has no line, spread/total has line,
  |               total selection is "over" or "under"
  |
  v
SqlAlchemyQuoteIngestionUnitOfWork (single transaction):
  |
  |-- _ensure_event(external_event_id, metadata)
  |     SELECT events WHERE external_id = ?
  |     If exists:
  |       UPDATE events SET sport, league, starts_at, provider
  |       DELETE event_participants WHERE event_id = ?
  |       INSERT event_participants (per participant in metadata)
  |     If not exists:
  |       INSERT events (id, external_id, sport, league, starts_at, provider, status)
  |       INSERT event_participants (per participant)
  |     Returns: internal event row ID (UUID)
  |
  |-- Per normalized quote:
  |     |
  |     |-- _ensure_market(event_row_id, quote)
  |     |     SELECT markets WHERE event_id, market_type, selection, line_key
  |     |     If not exists:
  |     |       INSERT markets (id, event_id, market_type, selection, line, line_key)
  |     |     Returns: (market_id, market_created: bool)
  |     |
  |     |-- DELETE market_quotes_latest WHERE market_id AND sportsbook
  |     |-- INSERT market_quotes_latest (market_id, sportsbook, price, quoted_at)
  |     |-- INSERT market_quotes_history (id, market_id, sportsbook, price, quoted_at)
  |     |
  |     |-- If market_created:
  |     |     Stage event: MarketSnapshotCreated
  |     |-- Stage event: QuoteUpdated
  |
  |-- Stage event: QuotesRefreshed (summary with counts)
  |
  |-- __exit__: persist staged events -> workflow_events table
  |-- __exit__: session.commit()
  |
  v
WorkflowEventPublisher.publish(committed_events)
  |  Current impl: LoggingWorkflowEventPublisher (structured log per event)
  |
  v
WatchIntentService.evaluate_for_event(event_id)    [POST-COMMIT HOOK]
  |
  |-- Check event.starts_at — skip if event already started
  |-- SELECT watch_intents WHERE event_external_id AND status='active'
  |-- SELECT market_quotes_latest + markets for this event
  |-- Get existing opportunity keys for deduplication
  |
  |-- WatchEvaluationEngine.evaluate()                          [PURE ENGINE]
  |     Per active watch intent:
  |       Filter quotes by: event_id, market_type, selection, line (exact match)
  |       Per matching quote:
  |         PriceComparisonService.is_price_fillable()          [PURE ENGINE]
  |           Rule: quote_price >= target_price (American odds)
  |         Dedup key: (watch_intent_id, market_id, sportsbook)
  |         If fillable AND not duplicate -> create Opportunity candidate
  |     Returns: list[Opportunity] (new only)
  |
  |-- INSERT opportunities (idempotent, DB uniqueness final guard)
  |-- Stage events: OpportunityIdentified (inserted rows only)
  |-- COMMIT -> PUBLISH
```

---

### Flow B — Watch Intent Creation (Stage 5)

```
POST /watch-intents
  {
    "event_id": "c6747886204aa9fee72f8f417533d92d",
    "market_type": "moneyline",
    "selection": "philadelphia flyers",
    "target_price": 120
  }
  |
  v
API Validation (watch_intent_schemas.py):
  - moneyline: line must be absent/null
  - spread/total: line required
  - total: selection must be "over" or "under"
  |
  v
WatchIntentService.create_watch_intent()
  |
  v
SqlAlchemyWatchIntentUnitOfWork (single transaction):
  |
  |-- INSERT watch_intents
  |     id=UUID, event_external_id, market_type, selection,
  |     line, target_price, status="active", created_at=NOW()
  |
  |-- Stage event: WatchIntentCreated
  |     payload: { event_id, market_type, selection, target_price, line }
  |
  |-- Immediate Evaluation (same logic as Flow A post-commit):
  |     SELECT market_quotes_latest for this event
  |     WatchEvaluationEngine.evaluate()
  |     INSERT opportunities (if fillable quotes found, duplicates ignored)
  |     Stage events: OpportunityIdentified (inserted rows only)
  |
  |-- COMMIT -> PUBLISH
  |
  v
Response 201:
  { id, event_id, market_type, selection, target_price, line, status: "active" }
```

---

### Flow C — Watch Intent Cancellation

```
DELETE /watch-intents/{watch_intent_id}
  |
  v
WatchIntentService.cancel_watch_intent()
  |
  v
SqlAlchemyWatchIntentUnitOfWork:
  |
  |-- UPDATE watch_intents SET status='cancelled' WHERE id=?
  |-- Stage event: WatchIntentCancelled
  |     payload: { event_id, market_type, selection }
  |-- COMMIT -> PUBLISH
  |
  v
Response 200: { id, status: "cancelled", ... }

NOTE: Existing opportunities are NOT deleted.
      Validity is computed at read time (Flow D).
```

---

### Flow D — Opportunity Listing with Computed Validity

```
GET /opportunities?event_id=c6747886204aa9fee72f8f417533d92d
  |
  v
WatchIntentService.list_opportunities()
  |
  v
SqlAlchemyWatchIntentUnitOfWork:
  |
  |-- SELECT opportunities
  |     JOIN watch_intents ON watch_intent_id
  |     WHERE event_external_id = ?
  |     -> Builds full Opportunity objects with market_type, selection, target_price, line
  |
  |-- Per opportunity:
  |     SELECT quoted_at FROM market_quotes_latest
  |       WHERE market_id = ? AND sportsbook = ?
  |     -> Returns latest_quote_time (or None if quote removed)
  |
  v
OpportunityValidityEngine.check_validity_batch()               [PURE ENGINE]
  |
  Per (opportunity, latest_quote_time):
    Check 1: opportunity.created_at is None
             -> is_valid=False, reason="missing_timestamp"
    Check 2: now - opportunity.created_at > TTL (default 5 min)
             -> is_valid=False, reason="expired"
    Check 3: latest_quote_time is None
             -> is_valid=False, reason="quote_removed"
    Check 4: latest_quote_time > opportunity.created_at
             -> is_valid=False, reason="quote_superseded"
    Check 5: All checks pass
             -> is_valid=True, reason=None
  |
  v
Response 200:
  {
    "opportunities": [
      {
        "id": "...",
        "watch_intent_id": "...",
        "sportsbook": "draftkings",
        "matched_price": 125,
        "market_type": "moneyline",
        "selection": "philadelphia flyers",
        "target_price": 120,
        "is_valid": true,
        "invalid_reason": null
      }
    ]
  }
```

---

## Database Schema

### Stages 5-6 Tables

```
events                           event_participants
+-----------------+              +------------------+
| id         (PK) |<----+       | id          (PK) |
| external_id (UQ)|     |       | event_id    (FK) |-------+
| sport            |     |       | participant_name |       |
| league           |     |       | role             |       |
| status           |     |       | side (nullable)  |       |
| provider         |     |       | sort_order       |       |
| starts_at        |     |       +------------------+       |
| created_at       |     |                                   |
+-----------------+     +-----------------------------------+
       |
       | event_id (FK)
       v
markets                          market_quotes_latest
+-----------------+              +------------------+
| id         (PK) |<-----+      | market_id   (PK) |---+
| event_id   (FK) |      |      | sportsbook  (PK) |   |
| market_type      |      |      | price            |   |
| selection        |      |      | quoted_at        |   |
| line (nullable)  |      |      +------------------+   |
| line_key         |      |                              |
| created_at       |      |      market_quotes_history   |
+-----------------+      |      +------------------+    |
  UQ(event_id,           |      | id          (PK) |    |
     market_type,        +------| market_id   (FK) |    |
     selection,                 | sportsbook       |    |
     line_key)                  | price            |    |
                                | quoted_at        |    |
                                +------------------+    |
                                                        |
watch_intents                    opportunities           |
+-----------------+              +------------------+    |
| id         (PK) |<-----+      | id          (PK) |    |
| event_external_id|      |      | watch_intent_id(FK)---+
| market_type      |      +------| event_external_id|    |
| selection        |             | market_id   (FK) |----+
| line (nullable)  |             | sportsbook       |
| target_price     |             | matched_price    |
| status           |             | created_at       |
| created_at       |             +------------------+
+-----------------+

workflow_events (append-only audit log for ALL domain events)
+-----------------+
| id          (PK) |
| event_type        |  "WatchIntentCreated", "OpportunityIdentified", etc.
| aggregate_id      |  The entity this event is about
| workflow_id       |  Groups related events in a single workflow
| payload     (JSON)|  Event-specific data
| occurred_at       |
| created_at        |
+-----------------+
```

### Table Relationships

- `events` 1:N `event_participants` (via event_id FK)
- `events` 1:N `markets` (via event_id FK)
- `markets` 1:N `market_quotes_latest` (via market_id FK, composite PK with sportsbook)
- `markets` 1:N `market_quotes_history` (via market_id FK)
- `watch_intents` 1:N `opportunities` (via watch_intent_id FK)
- `markets` 1:N `opportunities` (via market_id FK)

---

## Domain Events

### Stage 5 Events

| Event | Emitted When | Aggregate ID | Workflow ID |
|-------|-------------|-------------|-------------|
| **WatchIntentCreated** | POST /watch-intents | watch_intent_id | watch_intent_id |
| **WatchIntentCancelled** | DELETE /watch-intents/{id} | watch_intent_id | watch_intent_id |
| **OpportunityIdentified** | Watch creation OR quote refresh evaluation | opportunity_id | watch_intent_id |

### Stage 6 Events (already existed in Stage 4, now with live data)

| Event | Emitted When | Aggregate ID | Workflow ID |
|-------|-------------|-------------|-------------|
| **MarketSnapshotCreated** | New market discovered during ingestion | market_id | refresh_id |
| **QuoteUpdated** | Every quote persisted (1 per quote per sportsbook) | market_id | refresh_id |
| **QuotesRefreshed** | End of ingestion batch (1 per event refresh) | refresh_id | refresh_id |

### Event Payloads

```
WatchIntentCreated:
  { event_id, market_type, selection, target_price, line }

WatchIntentCancelled:
  { event_id, market_type, selection }

OpportunityIdentified:
  { watch_intent_id, event_id, market_type, selection,
    sportsbook, matched_price, target_price, line }

MarketSnapshotCreated:
  { event_id, market_type, selection, line }

QuoteUpdated:
  { event_id, market_type, selection, sportsbook, price, line }

QuotesRefreshed:
  { event_id, ingested_quote_count, created_market_count,
    updated_latest_count, appended_history_count }
```

### Event Lifecycle Pattern

All events follow: **Stage -> Persist -> Publish**

```
During UoW transaction:
  uow.stage_event(event)           # append to in-memory list

On UoW.__exit__ (no exception):
  _persist_staged_events()          # INSERT into workflow_events table
  session.commit()                  # atomic with data changes
  committed_events = staged_events  # snapshot for publisher

After commit:
  publisher.publish(committed_events)  # fire-and-forget (currently logging)

On UoW.__exit__ (exception):
  session.rollback()                # all data AND events discarded
  committed_events = ()             # nothing to publish
```

---

## Pure Engines (Zero I/O)

| Engine | Purpose | Inputs | Output |
|--------|---------|--------|--------|
| **NormalizationEngine** | Filter/validate raw quotes | event_id, list[Quote] | list[Quote] (valid only) |
| **WatchEvaluationEngine** | Match intents to quotes, produce opportunity candidates | intents, quotes, market_lookup, existing_keys | list[Opportunity] (candidate, prefiltered) |
| **OpportunityValidityEngine** | TTL + quote freshness checks | opportunity, latest_quote_time, ttl, now | OpportunityWithValidity |
| **PriceComparisonService** | Fillability check | quote_price, target_price | bool |

**Invariant:** Same input = same output. No database access, no HTTP calls, no side effects.

**Price Fillability Rule:** `quote_price >= target_price` (American odds — higher is better for bettor)
- `-105 >= -110` is True (better price)
- `+125 >= +120` is True (better price)
- `-115 >= -110` is False (worse price)

---

## State Transitions

### Watch Intent
```
(not exists) --[POST /watch-intents]--> active --[DELETE /watch-intents/{id}]--> cancelled
```

### Opportunity
```
(not exists) --[evaluation finds fillable quote]--> created
                                                      |
                              (validity computed at read time, never stored)
                                                      |
                              +--> is_valid=true  (within TTL, quote unchanged)
                              +--> expired        (older than TTL)
                              +--> quote_superseded (newer quote arrived)
                              +--> quote_removed  (sportsbook no longer quoting)
```

### Event (sporting event)
```
(not exists) --[first quote refresh]--> upcoming (metadata set)
                                           |
                              --[subsequent refreshes]--> metadata updated
                              (participants DELETE+re-INSERT each time)
```

### Market
```
(not exists) --[first quote for this event+type+selection+line]--> created
                                                                     |
                                                          (immutable after creation)
```

### Latest Quote
```
(not exists) --[first quote]--> created
     ^                            |
     |---[next refresh]--- DELETE + INSERT (upsert pattern)
```

### History Quote
```
(not exists) --[every quote ingested]--> appended (never modified or deleted)
```

---

## Interaction Between Stages 5 and 6

The critical integration point is the **post-ingestion watch evaluation hook**:

```
QuoteIngestionService.refresh_quotes()
  |
  | (after successful commit of quote data)
  |
  v
if watch_intent_service is not None:
    watch_intent_service.evaluate_for_event(event_id)
```

This means:
1. **Every quote refresh** (whether single-event or sport-level) triggers watch evaluation
2. New opportunities are created if any active watch intent's target price is met by newly ingested quotes
3. Failure in watch evaluation does NOT roll back the quote ingestion (separate transaction, caught exception)
4. Deduplication prevents the same opportunity from being created on repeated refreshes

---

## API Endpoints (Stages 5-6)

| Method | Path | Purpose | Events Emitted |
|--------|------|---------|---------------|
| POST | `/watch-intents` | Create watch intent + immediate evaluation | WatchIntentCreated, OpportunityIdentified* |
| GET | `/watch-intents?event_id=` | List active intents (filters by event start time) | (none) |
| DELETE | `/watch-intents/{id}` | Cancel watch intent | WatchIntentCancelled |
| GET | `/opportunities?event_id=` | List opportunities with computed validity | (none) |
| POST | `/ingestion/quotes/refresh-sport` | Refresh all events for a sport from Odds API | MarketSnapshotCreated*, QuoteUpdated, QuotesRefreshed, OpportunityIdentified* |

*\* = emitted conditionally (only when new markets/opportunities are found)*

---

## Provider Abstraction

Both providers implement the same Protocol interface:

```
QuoteIngestionProvider (Protocol):
  list_quotes(event_id: str) -> list[Quote]
  list_quotes_for_sport(sport: str) -> dict[str, list[Quote]]
  get_event_info(event_id: str) -> EventInfo | None
```

| Provider | Data Source | Used When |
|----------|------------|-----------|
| TheOddsApiProvider | Live HTTP API | QUOTE_PROVIDER=odds_api |
| InMemoryQuoteProvider | Hardcoded fixtures (NBA Knicks vs Celtics) | QUOTE_PROVIDER=in_memory (default) |

### Sport/League Parsing (Odds API)

```
"icehockey_nhl"       -> sport="ice_hockey",       league="NHL"
"baseball_mlb"        -> sport="baseball",          league="MLB"
"basketball_nba"      -> sport="basketball",        league="NBA"
"americanfootball_nfl"-> sport="american_football",  league="NFL"
"soccer_epl"          -> sport="soccer",            league="EPL"
"golf_pga"            -> sport="golf",              league="PGA"
"tennis_atp"          -> sport="tennis",            league="ATP"
```
