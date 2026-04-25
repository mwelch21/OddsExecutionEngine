# Rework Event Schema: Flexible Participants Model

## Context

The current `events` table has `home_team` and `away_team` columns — rigid for team sports only. This breaks for golf, tennis, player props, or any format without exactly 2 teams. Reworking now before more code depends on these columns.

**New design:**
- `events` gets `sport`, `league`, `status`, drops `home_team`/`away_team`
- New `event_participants` table with `participant_name` as string (easy to normalize to a reference table later)
- `EventInfo` domain model updated to carry a list of participants instead of home/away

---

## Schema Changes

### `events` table (after migration)

| Column | Type | Notes |
|--------|------|-------|
| id | varchar(36) PK | |
| external_id | varchar(255) UNIQUE | Odds API event ID or fixture ID |
| sport | varchar(64) nullable | e.g. "ice_hockey", "baseball" |
| league | varchar(64) nullable | e.g. "NHL", "MLB", "PGA" |
| status | varchar(16) default "upcoming" | upcoming, live, completed, cancelled |
| provider | varchar(32) nullable | "TheOddsApiProvider", "InMemoryQuoteProvider" |
| starts_at | timestamp with tz nullable | |
| created_at | timestamp with tz | |

### `event_participants` table (new)

| Column | Type | Notes |
|--------|------|-------|
| id | varchar(36) PK | |
| event_id | varchar(36) FK events.id | |
| participant_name | varchar(128) | "Pittsburgh Penguins", "Tiger Woods" |
| role | varchar(32) | "team", "player", "selection" |
| side | varchar(16) nullable | "home", "away", null (for golf/tennis) |
| sort_order | integer default 0 | Display ordering |

---

## Files to Modify

### Migration
**`backend/db/migrations/versions/20260420_0004_stage6_event_metadata.py`** — rewrite:
- DROP `home_team`, `away_team` from events (they were never applied to Docker DB, so this is safe)
- ADD `league` varchar(64) nullable
- ADD `status` varchar(16) default "upcoming"
- Keep `sport`, `provider` (already in migration)
- CREATE `event_participants` table

### Schema
**`backend/app/infrastructure/persistence/schema.py`**:
- Remove `home_team`, `away_team` columns from `events_table`
- Add `league`, `status` columns
- Add `event_participants_table`

### Domain Model
**`backend/app/domain/models.py`** — rework `EventInfo`:
```python
class EventParticipant(DomainModel):
    name: str
    role: str        # "team", "player", "selection"
    side: str | None = None   # "home", "away", None
    sort_order: int = 0

class EventInfo(DomainModel):
    id: str
    sport: str
    league: str | None = None
    status: str = "upcoming"
    participants: list[EventParticipant] = []
    commence_time: datetime | None = None
```

### Providers
**`backend/app/infrastructure/odds_api_provider.py`** — `_cache_event`:
- Map `home_team` / `away_team` from API to `EventParticipant` objects
- Extract league from sport key (e.g. `"icehockey_nhl"` → sport=`"ice_hockey"`, league=`"NHL"`)

**`backend/app/infrastructure/quote_provider.py`** — `_build_fixture_events`:
- Update fixture EventInfo to use participants list

### Ingestion Service
**`backend/app/application/quote_ingestion_service.py`** — `refresh_sport`:
- Change metadata dict: drop `home_team`/`away_team`, add `league`, `status`
- Pass participants separately to UoW

### Ingestion UoW
**`backend/app/infrastructure/persistence/quote_ingestion_uow.py`** — `_ensure_event`:
- Handle `participants` in metadata — insert into `event_participants` table
- On update: delete existing participants and re-insert (simple upsert)

### Seed
**`backend/app/infrastructure/persistence/seed.py`**:
- Add `event_participants_table` to imports and truncation order
- Insert participant rows for fixture event

### Tests
**`backend/tests/test_odds_api_provider.py`**:
- Update assertions: `home_team`/`away_team` → `participants` list
- Check participant roles and sides

**`backend/tests/test_app.py`**:
- Update expected table list (add `event_participants`)

---

## Sport/League Mapping

The Odds API uses combined keys like `icehockey_nhl`. We split them:

| API Key | sport | league |
|---------|-------|--------|
| `icehockey_nhl` | `ice_hockey` | `NHL` |
| `baseball_mlb` | `baseball` | `MLB` |
| `basketball_nba` | `basketball` | `NBA` |
| `americanfootball_nfl` | `american_football` | `NFL` |

Simple split on `_` — last segment uppercased = league, rest = sport (underscores preserved).

---

## Verification

1. `uv run pytest` — all 71+ tests pass
2. `uv run odds-db-upgrade` — migration applies cleanly
3. `docker compose up -d --build` then refresh NHL — participants show in DB
4. `docker compose exec postgres psql -U app -d odds_execution -c "SELECT * FROM event_participants LIMIT 5;"` — verify rows
5. Existing watch intent + opportunity flows unaffected
