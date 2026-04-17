#!/usr/bin/env bash

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

PASS=0
FAIL=0
TOTAL=0
CLEANUP=false
SKIP_BUILD=false
BASE_URL="http://localhost:8000"

for arg in "$@"; do
  case "$arg" in
    --cleanup) CLEANUP=true ;;
    --skip-build) SKIP_BUILD=true ;;
  esac
done

GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[0;33m'
NC='\033[0m'

log() {
  printf '\n[%s] %s\n' "integration-test" "$1"
}

run_test() {
  local name="$1"
  shift
  TOTAL=$((TOTAL + 1))
  if "$@" >/dev/null 2>&1; then
    PASS=$((PASS + 1))
    printf "  ${GREEN}PASS${NC}  %s\n" "$name"
  else
    FAIL=$((FAIL + 1))
    printf "  ${RED}FAIL${NC}  %s\n" "$name"
  fi
}

assert_json() {
  local payload="$1"
  local script="$2"
  python3 -c "import json; data=json.loads('''$payload'''); $script"
}

assert_equals() {
  local actual="$1"
  local expected="$2"
  [[ "$actual" == "$expected" ]]
}

assert_gte() {
  local actual="$1"
  local minimum="$2"
  [[ "$actual" -ge "$minimum" ]]
}

post_json() {
  local path="$1"
  local payload="$2"
  curl -sS -X POST "${BASE_URL}${path}" \
    -H "content-type: application/json" \
    -d "$payload"
}

get_status() {
  local method="$1"
  local path="$2"
  local payload="${3:-}"
  if [[ "$method" == "GET" ]]; then
    curl -sS -o /dev/null -w '%{http_code}' "${BASE_URL}${path}"
  else
    curl -sS -o /dev/null -w '%{http_code}' -X POST "${BASE_URL}${path}" \
      -H "content-type: application/json" \
      -d "$payload"
  fi
}

get_header() {
  local path="$1"
  local header="$2"
  local payload="${3:-}"
  local extra_headers="${4:-}"
  if [[ -n "$payload" ]]; then
    curl -sS -D - -o /dev/null -X POST "${BASE_URL}${path}" \
      -H "content-type: application/json" \
      ${extra_headers:+-H "$extra_headers"} \
      -d "$payload" | grep -i "^${header}:" | awk '{print $2}' | tr -d '\r\n'
  else
    curl -sS -D - -o /dev/null "${BASE_URL}${path}" \
      ${extra_headers:+-H "$extra_headers"} | grep -i "^${header}:" | awk '{print $2}' | tr -d '\r\n'
  fi
}

query_count() {
  local table="$1"
  docker compose exec -T postgres psql -U app -d odds_execution -tAc "select count(*) from ${table};" \
    | tr -d '[:space:]'
}

wait_for_api() {
  log "waiting for API to be ready"
  local attempts=0
  local max_attempts=30
  while [[ $attempts -lt $max_attempts ]]; do
    if curl -sS -o /dev/null -w '' "${BASE_URL}/health" 2>/dev/null; then
      log "API ready"
      return 0
    fi
    attempts=$((attempts + 1))
    sleep 1
  done
  log "API failed to start after ${max_attempts}s"
  return 1
}

cleanup() {
  if [[ "$CLEANUP" == "true" ]]; then
    log "cleaning up containers"
    docker compose down -v
  fi
}

trap cleanup EXIT

# ---------------------------------------------------------------------------
# Infrastructure setup
# ---------------------------------------------------------------------------

log "starting containers"
if [[ "$SKIP_BUILD" == "true" ]]; then
  docker compose up -d
else
  docker compose up --build -d
fi

wait_for_api

log "running migrations"
docker compose exec -T api uv run alembic -c backend/db/alembic.ini upgrade head

log "seeding demo quotes"
docker compose exec -T api uv run odds-db-seed-demo

# ---------------------------------------------------------------------------
# Test group 1: Health check
# ---------------------------------------------------------------------------

log "health check tests"

test_health_ok() {
  local response
  response="$(curl -sS "${BASE_URL}/health")"
  assert_json "$response" "assert data['status'] == 'ok'; assert data['environment'] == 'development'"
}

test_health_request_id_generated() {
  local header
  header="$(get_header "/health" "X-Request-ID")"
  [[ -n "$header" ]]
}

test_health_request_id_propagated() {
  local header
  header="$(curl -sS -D - -o /dev/null "${BASE_URL}/health" \
    -H "X-Request-ID: integration-trace-001" | grep -i "^X-Request-ID:" | awk '{print $2}' | tr -d '\r\n')"
  assert_equals "$header" "integration-trace-001"
}

run_test "GET /health returns ok" test_health_ok
run_test "GET /health generates X-Request-ID" test_health_request_id_generated
run_test "GET /health propagates X-Request-ID" test_health_request_id_propagated

# ---------------------------------------------------------------------------
# Test group 2: Quote ingestion
# ---------------------------------------------------------------------------

log "quote ingestion tests"

test_ingestion_refresh() {
  local response
  response="$(post_json "/ingestion/quotes/refresh" '{"event_id":"nba-knicks-celtics-2026-04-11"}')"
  assert_json "$response" "\
assert data['event_id'] == 'nba-knicks-celtics-2026-04-11'; \
assert data['ingested_quote_count'] == 10; \
assert data['updated_latest_count'] == 10; \
assert data['appended_history_count'] == 10; \
assert len(data['emitted_event_types']) > 0"
}

test_ingestion_emits_expected_event_types() {
  local response
  response="$(post_json "/ingestion/quotes/refresh" '{"event_id":"nba-knicks-celtics-2026-04-11"}')"
  assert_json "$response" "\
types = data['emitted_event_types']; \
assert 'QuotesRefreshed' in types; \
assert 'QuoteUpdated' in types"
}

test_ingestion_empty_event_id_rejected() {
  local status
  status="$(get_status POST "/ingestion/quotes/refresh" '{"event_id":""}')"
  assert_equals "$status" "422"
}

run_test "POST /ingestion/quotes/refresh returns counts" test_ingestion_refresh
run_test "POST /ingestion/quotes/refresh emits expected event types" test_ingestion_emits_expected_event_types
run_test "POST /ingestion/quotes/refresh rejects empty event_id" test_ingestion_empty_event_id_rejected

# ---------------------------------------------------------------------------
# Test group 3: Recommendation scenarios
# ---------------------------------------------------------------------------

log "recommendation tests"

test_fillable_moneyline() {
  local response
  response="$(post_json "/execution/recommendation" \
    '{"event_id":"nba-knicks-celtics-2026-04-11","market_type":"moneyline","selection":"knicks","target_price":121}')"
  assert_json "$response" "\
assert data['fillable'] is True; \
assert data['best_quote']['sportsbook'] == 'DraftKings'; \
assert data['best_quote']['price'] == 125; \
assert data['matched_quote_count'] == 3; \
assert data['nearest_miss'] is None"
}

test_unfillable_total() {
  local response
  response="$(post_json "/execution/recommendation" \
    '{"event_id":"nba-knicks-celtics-2026-04-11","market_type":"total","selection":"over","line":221.5,"target_price":-105}')"
  assert_json "$response" "\
assert data['fillable'] is False; \
assert data['best_quote']['price'] == -108; \
assert data['nearest_miss']['price'] == -108; \
assert data['matched_quote_count'] == 2"
}

test_unmatched_spread() {
  local response
  response="$(post_json "/execution/recommendation" \
    '{"event_id":"nba-knicks-celtics-2026-04-11","market_type":"spread","selection":"knicks","line":6.5,"target_price":-110}')"
  assert_json "$response" "\
assert data['fillable'] is False; \
assert data['best_quote'] is None; \
assert data['nearest_miss'] is None; \
assert data['ranked_quotes'] == []; \
assert data['matched_quote_count'] == 0"
}

test_unknown_event() {
  local response
  response="$(post_json "/execution/recommendation" \
    '{"event_id":"nonexistent-event","market_type":"moneyline","selection":"knicks","target_price":100}')"
  assert_json "$response" "\
assert data['fillable'] is False; \
assert data['matched_quote_count'] == 0; \
assert data['ranked_quotes'] == []"
}

run_test "Fillable moneyline recommendation" test_fillable_moneyline
run_test "Unfillable total recommendation" test_unfillable_total
run_test "Unmatched spread recommendation" test_unmatched_spread
run_test "Unknown event recommendation" test_unknown_event

# ---------------------------------------------------------------------------
# Test group 4: Validation failures
# ---------------------------------------------------------------------------

log "validation tests"

test_invalid_total_selection() {
  local status
  status="$(get_status POST "/execution/recommendation" \
    '{"event_id":"nba-knicks-celtics-2026-04-11","market_type":"total","selection":"knicks","line":221.5,"target_price":-110}')"
  assert_equals "$status" "422"
}

test_moneyline_with_line() {
  local status
  status="$(get_status POST "/execution/recommendation" \
    '{"event_id":"nba-knicks-celtics-2026-04-11","market_type":"moneyline","selection":"knicks","line":1.5,"target_price":120}')"
  assert_equals "$status" "422"
}

test_missing_required_fields() {
  local status
  status="$(get_status POST "/execution/recommendation" '{}')"
  assert_equals "$status" "422"
}

test_spread_missing_line() {
  local status
  status="$(get_status POST "/execution/recommendation" \
    '{"event_id":"nba-knicks-celtics-2026-04-11","market_type":"spread","selection":"knicks","target_price":-110}')"
  assert_equals "$status" "422"
}

run_test "Rejects invalid total selection" test_invalid_total_selection
run_test "Rejects moneyline with line" test_moneyline_with_line
run_test "Rejects missing required fields" test_missing_required_fields
run_test "Rejects spread without line" test_spread_missing_line

# ---------------------------------------------------------------------------
# Test group 5: X-Request-ID on recommendation
# ---------------------------------------------------------------------------

log "tracing tests"

test_recommendation_request_id() {
  local header
  header="$(curl -sS -D - -o /dev/null -X POST "${BASE_URL}/execution/recommendation" \
    -H "content-type: application/json" \
    -H "X-Request-ID: rec-trace-001" \
    -d '{"event_id":"nba-knicks-celtics-2026-04-11","market_type":"moneyline","selection":"knicks","target_price":121}' \
    | grep -i "^X-Request-ID:" | awk '{print $2}' | tr -d '\r\n')"
  assert_equals "$header" "rec-trace-001"
}

run_test "Recommendation propagates X-Request-ID" test_recommendation_request_id

# ---------------------------------------------------------------------------
# Test group 6: Database state
# ---------------------------------------------------------------------------

log "database state tests"

test_events_count() {
  local count
  count="$(query_count events)"
  assert_gte "$count" 1
}

test_markets_count() {
  local count
  count="$(query_count markets)"
  assert_equals "$count" "6"
}

test_quotes_latest_count() {
  local count
  count="$(query_count market_quotes_latest)"
  assert_equals "$count" "10"
}

test_quotes_history_count() {
  local count
  count="$(query_count market_quotes_history)"
  assert_gte "$count" 20
}

test_order_intents_count() {
  local count
  count="$(query_count order_intents)"
  assert_gte "$count" 4
}

test_execution_recommendations_count() {
  local count
  count="$(query_count execution_recommendations)"
  assert_gte "$count" 4
}

test_workflow_events_count() {
  local count
  count="$(query_count workflow_events)"
  assert_gte "$count" 1
}

run_test "events table has rows" test_events_count
run_test "markets table has 6 rows" test_markets_count
run_test "market_quotes_latest has 10 rows" test_quotes_latest_count
run_test "market_quotes_history has >= 20 rows" test_quotes_history_count
run_test "order_intents has >= 4 rows" test_order_intents_count
run_test "execution_recommendations has >= 4 rows" test_execution_recommendations_count
run_test "workflow_events has rows" test_workflow_events_count

# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------

printf '\n%s\n' "============================================"
if [[ "$FAIL" -eq 0 ]]; then
  printf "${GREEN}Passed: %d / %d${NC}\n" "$PASS" "$TOTAL"
else
  printf "${RED}Passed: %d / %d  (${FAIL} failed)${NC}\n" "$PASS" "$TOTAL"
fi
printf '%s\n' "============================================"

[[ "$FAIL" -eq 0 ]]
