#!/usr/bin/env bash

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

log() {
  printf '\n[%s] %s\n' "verify-stage2.5" "$1"
}

assert_json() {
  local payload="$1"
  local script="$2"
  python3 -c "import json; data=json.loads('''$payload'''); $script"
}

assert_equals() {
  local actual="$1"
  local expected="$2"
  local label="$3"
  if [[ "$actual" != "$expected" ]]; then
    printf 'Assertion failed for %s: expected %s, got %s\n' "$label" "$expected" "$actual" >&2
    exit 1
  fi
}

post_json() {
  local payload="$1"
  curl -sS -X POST http://localhost:8000/execution/recommendation \
    -H "content-type: application/json" \
    -d "$payload"
}

query_count() {
  local table="$1"
  docker compose exec -T postgres psql -U app -d odds_execution -tAc "select count(*) from ${table};" \
    | tr -d '[:space:]'
}

log "starting containers"
docker compose up --build -d

log "running migrations"
docker compose exec -T api uv run alembic -c backend/db/alembic.ini upgrade head

log "seeding demo quotes"
docker compose exec -T api uv run odds-db-seed-demo

log "checking health endpoint"
health_response="$(curl -sS http://localhost:8000/health)"
assert_json "$health_response" "assert data['status'] == 'ok'; assert data['environment'] == 'development'"

log "checking fillable moneyline recommendation"
fillable_response="$(post_json '{"event_id":"nba-knicks-celtics-2026-04-11","market_type":"moneyline","selection":"knicks","target_price":121}')"
assert_json "$fillable_response" "assert data['fillable'] is True; assert data['best_quote']['sportsbook'] == 'DraftKings'; assert data['best_quote']['price'] == 125; assert data['matched_quote_count'] == 3; assert data['nearest_miss'] is None"

log "checking unfillable total recommendation"
unfillable_response="$(post_json '{"event_id":"nba-knicks-celtics-2026-04-11","market_type":"total","selection":"over","line":221.5,"target_price":-105}')"
assert_json "$unfillable_response" "assert data['fillable'] is False; assert data['best_quote']['price'] == -108; assert data['nearest_miss']['price'] == -108; assert data['matched_quote_count'] == 2"

log "checking unmatched spread recommendation"
empty_response="$(post_json '{"event_id":"nba-knicks-celtics-2026-04-11","market_type":"spread","selection":"knicks","line":6.5,"target_price":-110}')"
assert_json "$empty_response" "assert data['fillable'] is False; assert data['best_quote'] is None; assert data['nearest_miss'] is None; assert data['ranked_quotes'] == []; assert data['matched_quote_count'] == 0"

log "checking invalid total selection validation"
invalid_total_status="$(curl -sS -o /dev/null -w '%{http_code}' -X POST http://localhost:8000/execution/recommendation \
  -H 'content-type: application/json' \
  -d '{"event_id":"nba-knicks-celtics-2026-04-11","market_type":"total","selection":"knicks","line":221.5,"target_price":-110}')"
assert_equals "$invalid_total_status" "422" "invalid total selection status"

log "checking invalid moneyline line validation"
invalid_moneyline_status="$(curl -sS -o /dev/null -w '%{http_code}' -X POST http://localhost:8000/execution/recommendation \
  -H 'content-type: application/json' \
  -d '{"event_id":"nba-knicks-celtics-2026-04-11","market_type":"moneyline","selection":"knicks","line":1.5,"target_price":120}')"
assert_equals "$invalid_moneyline_status" "422" "invalid moneyline line status"

log "checking persisted seed counts"
assert_equals "$(query_count events)" "1" "events count"
assert_equals "$(query_count markets)" "6" "markets count"
assert_equals "$(query_count market_quotes_latest)" "10" "market_quotes_latest count"
assert_equals "$(query_count market_quotes_history)" "10" "market_quotes_history count"

log "checking persisted recommendation rows"
order_intents_count="$(query_count order_intents)"
execution_recommendations_count="$(query_count execution_recommendations)"
if [[ "$order_intents_count" -lt 3 ]]; then
  printf 'Expected at least 3 order intents, got %s\n' "$order_intents_count" >&2
  exit 1
fi
if [[ "$execution_recommendations_count" -lt 3 ]]; then
  printf 'Expected at least 3 execution recommendations, got %s\n' "$execution_recommendations_count" >&2
  exit 1
fi

log "stage 2.5 verification passed"
