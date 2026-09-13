#!/usr/bin/env bash
# Manual validation harness.
#
# Tracked tooling, so it arrives in every worktree through git and a fresh
# worktree can run a suite without copying anything in.
#
# Per-suite configuration is NOT tracked. It lives in the suite directory at
# .manual-validation/<branch-slug>/env.sh, which is regenerated per suite --
# that is exactly why copying it between branches was never safe.
#
# Ports resolve through scripts/lib/stack-env.sh, so this always talks to THIS
# worktree's stack. It used to need a private compose override to dodge a
# hardcoded Postgres host port; docker-compose.yml is configurable now, so the
# override is gone.
#
# Every subcommand is safe to re-run except `reset-db`, which is destructive and
# is only ever invoked from the explicit "Reset local DB" cell.

set -euo pipefail

MV_REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$MV_REPO_ROOT"

# shellcheck source=../lib/stack-env.sh
source "${MV_REPO_ROOT}/scripts/lib/stack-env.sh"

MV_BRANCH_SLUG="${MV_BRANCH_SLUG:-$(git rev-parse --abbrev-ref HEAD | tr '/' '-')}"
MV_SUITE_DIR="${MV_SUITE_DIR:-${MV_REPO_ROOT}/.manual-validation/${MV_BRANCH_SLUG}}"
if [[ -f "${MV_SUITE_DIR}/env.sh" ]]; then
  # shellcheck source=/dev/null
  source "${MV_SUITE_DIR}/env.sh"
fi
MV_RESULTS="${MV_RESULTS:-${MV_SUITE_DIR}/results}"
EVENT_ID="${EVENT_ID:-nba-knicks-celtics-2026-04-11}"
export MV_REPO_ROOT MV_BRANCH_SLUG MV_SUITE_DIR MV_RESULTS EVENT_ID
mkdir -p "$MV_RESULTS"

dc() {
  docker compose -f "${MV_REPO_ROOT}/docker-compose.yml" "$@"
}

psql_q() {
  dc exec -T postgres psql -U app -d odds_execution "$@"
}

api() {
  local method="$1" path="$2" body="${3:-}"
  if [[ -n "$body" ]]; then
    curl -sS -X "$method" "${BASE_URL}${path}" \
      -H 'content-type: application/json' -d "$body"
  else
    curl -sS -X "$method" "${BASE_URL}${path}"
  fi
}

api_status() {
  local method="$1" path="$2" body="${3:-}"
  if [[ -n "$body" ]]; then
    curl -sS -o /dev/null -w '%{http_code}' -X "$method" "${BASE_URL}${path}" \
      -H 'content-type: application/json' -d "$body"
  else
    curl -sS -o /dev/null -w '%{http_code}' -X "$method" "${BASE_URL}${path}"
  fi
}

MV_FAILURES=0

expect_status() {
  local label="$1" actual="$2" expected="$3"
  if [[ "$actual" == "$expected" ]]; then
    printf '  PASS  %s (HTTP %s)\n' "$label" "$actual"
  else
    printf '  FAIL  %s (HTTP %s, expected %s)\n' "$label" "$actual" "$expected"
    MV_FAILURES=$((MV_FAILURES + 1))
  fi
}

expect_eq() {
  local label="$1" actual="$2" expected="$3"
  if [[ "$actual" == "$expected" ]]; then
    printf '  PASS  %s = %s\n' "$label" "$actual"
  else
    printf '  FAIL  %s = %s, expected %s\n' "$label" "$actual" "$expected"
    MV_FAILURES=$((MV_FAILURES + 1))
  fi
}

wait_for_api() {
  local attempts=0
  until curl -sS -o /dev/null "${BASE_URL}/health" 2>/dev/null; do
    attempts=$((attempts + 1))
    if [[ $attempts -ge 40 ]]; then
      echo "API did not come up at ${BASE_URL}" >&2
      return 1
    fi
    sleep 1
  done
  echo "API ready at ${BASE_URL}"
}

# `upgrade head` dies opaquely when the DB is stamped at a revision this checkout
# has never heard of. Diagnose it instead, and DO NOT guess at a single cause --
# the usual reason is benign (you switched to an older branch), and the remedy for
# that is not the destructive one.
check_schema_reachable() {
  local current
  current="$(psql_q -tAc \
    "select version_num from alembic_version" 2>/dev/null || echo "")"
  if [[ -z "$current" ]]; then
    return 0
  fi
  if ! ls backend/db/migrations/versions/*.py >/dev/null 2>&1; then
    return 0
  fi
  if grep -qs "revision = \"${current}\"" backend/db/migrations/versions/*.py; then
    return 0
  fi

  local branch owning
  branch="$(git rev-parse --abbrev-ref HEAD 2>/dev/null || echo '?')"
  # Does any branch in the repo carry this revision?
  owning="$(git grep -l "revision = \"${current}\"" \
    $(git for-each-ref --format='%(refname:short)' refs/heads) \
    -- backend/db/migrations/versions 2>/dev/null | cut -d: -f1 | sort -u | paste -sd, -)"

  cat >&2 <<MSG

  The local DB is stamped at revision '${current}', which does not exist in
  backend/db/migrations/versions/ on the branch you have checked out (${branch}).
  Alembic cannot migrate forward from a revision it cannot find.

MSG
  if [[ -n "$owning" ]]; then
    cat >&2 <<MSG
  That revision DOES exist on: ${owning}

  So this is almost certainly just a branch switch -- the database was migrated
  by a newer branch than the one you are on. Nothing is broken. Either:

      git checkout <one of those branches>      # and re-run this cell
      \$MV sql "select version_num from alembic_version;"   # to confirm

  Only reach for '\$MV reset-db' (which DESTROYS the local volume) if you
  actually want this branch's schema instead.

MSG
  else
    cat >&2 <<MSG
  No branch in this repo defines that revision, so it was probably renamed or
  removed after the database was migrated. Rebuild the local volume:

      \$MV reset-db      # DESTRUCTIVE: drops the local Postgres volume

MSG
  fi
  return 1
}

cmd_up() {
  dc up --build -d
  wait_for_api
  check_schema_reachable
  dc exec -T api uv run alembic -c backend/db/alembic.ini upgrade head
  dc exec -T api uv run odds-db-seed-demo
  echo "stack up, schema migrated, demo quotes seeded"
}

cmd_down() {
  dc down
  echo "containers stopped (volumes kept)"
}

# Destructive. Only called from the explicit reset cell.
cmd_reset_db() {
  dc down -v
  dc up --build -d
  wait_for_api
  dc exec -T api uv run alembic -c backend/db/alembic.ini upgrade head
  dc exec -T api uv run odds-db-seed-demo
  rm -f "${MV_RESULTS}"/*.json "${MV_RESULTS}"/*.txt 2>/dev/null || true
  echo "local DB volume destroyed, stack rebuilt, demo quotes seeded, results cleared"
}

# Clears watches/opportunities/events but keeps the seeded market data, so the
# suite can be re-run without a full volume rebuild.
cmd_clear_watches() {
  psql_q -c "delete from opportunities; delete from watch_intents; delete from workflow_events;"
  rm -f "${MV_RESULTS}"/*.json "${MV_RESULTS}"/*.txt 2>/dev/null || true
  echo "watches, opportunities and workflow events cleared; market data kept"
}

past_timestamp() {
  date -u -v-5M +%Y-%m-%dT%H:%M:%SZ 2>/dev/null \
    || date -u -d '5 minutes ago' +%Y-%m-%dT%H:%M:%SZ
}

# create-watch <target_price> [expires_at] [slot]
cmd_create_watch() {
  local target_price="$1" expires_at="${2:-}" slot="${3:-watch}"
  local body
  if [[ -n "$expires_at" ]]; then
    body="$(jq -nc --arg e "$EVENT_ID" --argjson t "$target_price" --arg x "$expires_at" \
      '{event_id:$e, market_type:"moneyline", selection:"knicks", target_price:$t, expires_at:$x}')"
  else
    body="$(jq -nc --arg e "$EVENT_ID" --argjson t "$target_price" \
      '{event_id:$e, market_type:"moneyline", selection:"knicks", target_price:$t}')"
  fi
  api POST /watch-intents "$body" | tee "${MV_RESULTS}/${slot}.json" | jq .
  jq -r .id "${MV_RESULTS}/${slot}.json" > "${MV_RESULTS}/${slot}_id.txt"
}

watch_id() {
  cat "${MV_RESULTS}/${1:-watch}_id.txt"
}

cmd_refresh() {
  api POST /ingestion/quotes/refresh "$(jq -nc --arg e "$EVENT_ID" '{event_id:$e}')" \
    | tee "${MV_RESULTS}/refresh.json" | jq .
}

cmd_watch() {
  api GET "/watch-intents/$(watch_id "${1:-watch}")" | jq .
}

cmd_opportunities() {
  api GET "/opportunities?event_id=${EVENT_ID}" \
    | tee "${MV_RESULTS}/opportunities.json" | jq .
}

# opportunity-for <slot> -> the single opportunity belonging to that watch
cmd_opportunity_for() {
  local slot="${1:-watch}"
  api GET "/opportunities?event_id=${EVENT_ID}" \
    | jq --arg w "$(watch_id "$slot")" \
        '.opportunities[] | select(.watch_intent_id == $w)'
}

# bump-quote <sportsbook> -- make that book's latest quote newer than the
# opportunity, which is how staleness is detected.
cmd_bump_quote() {
  local book="$1"
  psql_q -c "update market_quotes_latest set quoted_at = now() + interval '1 second' where sportsbook = '${book}';"
  echo "bumped quoted_at for ${book}"
}

# events-for <event_type> <watch_id> -- events belonging to ONE watch.
# OpportunityIdentified carries the watch in its payload; the watch lifecycle
# events carry it as aggregate_id.
count_events_for_watch() {
  local event_type="$1" wid="$2"
  psql_q -tAc "select count(*) from workflow_events
    where event_type = '${event_type}'
      and (aggregate_id = '${wid}' or payload->>'watch_intent_id' = '${wid}');" | tr -d ' '
}

cmd_events() {
  psql_q -c "select event_type, count(*) from workflow_events group by event_type order by 1;"
}

cmd_sql() {
  psql_q -c "$1"
}

cmd_full() {
  # Self-contained: a stale watch or event from an earlier run would otherwise
  # make the per-watch counts below ambiguous.
  cmd_clear_watches >/dev/null

  echo "== 1. watch at +100: three books qualify (DK 125, FD 125, BetMGM 120) =="
  cmd_create_watch 100 "" watch >/dev/null
  echo "   watch id $(watch_id watch)"

  echo
  echo "== 2. creation evaluated immediately and returned the whole answer =="
  expect_eq "status on create" \
    "$(jq -r .status "${MV_RESULTS}/watch.json")" "triggered"
  expect_eq "opportunity nested in create response" \
    "$(jq -r '.opportunity != null' "${MV_RESULTS}/watch.json")" "true"
  expect_eq "best book (DK/FD tie broken alphabetically)" \
    "$(jq -r .opportunity.best_sportsbook "${MV_RESULTS}/watch.json")" "DraftKings"
  expect_eq "books carried in the snapshot" \
    "$(jq -r '[.opportunity.matching_quotes[].sportsbook] | join(",")' "${MV_RESULTS}/watch.json")" \
    "DraftKings,FanDuel,BetMGM"

  echo
  echo "== 3. THE POINT OF #17: three books, one opportunity, one notification =="
  cmd_opportunities >/dev/null
  expect_eq "opportunity rows for this watch" \
    "$(jq --arg w "$(watch_id watch)" \
        '[.opportunities[] | select(.watch_intent_id == $w)] | length' \
        "${MV_RESULTS}/opportunities.json")" "1"
  expect_eq "OpportunityIdentified events (was 3 before #17)" \
    "$(count_events_for_watch OpportunityIdentified "$(watch_id watch)")" "1"
  expect_eq "WatchIntentTriggered audit event" \
    "$(count_events_for_watch WatchIntentTriggered "$(watch_id watch)")" "1"

  echo
  echo "== 4. the watch is terminal: further refreshes do not re-evaluate it =="
  cmd_refresh >/dev/null
  cmd_refresh >/dev/null
  expect_eq "status after two more refreshes" \
    "$(api GET "/watch-intents/$(watch_id watch)" | jq -r .status)" "triggered"
  expect_eq "still exactly one opportunity" \
    "$(api GET "/opportunities?event_id=${EVENT_ID}" | jq --arg w "$(watch_id watch)" \
        '[.opportunities[] | select(.watch_intent_id == $w)] | length')" "1"
  expect_eq "still exactly one notification" \
    "$(count_events_for_watch OpportunityIdentified "$(watch_id watch)")" "1"

  echo
  echo "== 5. it went stale, and still did not re-arm =="
  expect_eq "opportunity now reported stale" \
    "$(cmd_opportunity_for watch | jq -r .is_valid)" "false"
  expect_eq "watch status unchanged" \
    "$(api GET "/watch-intents/$(watch_id watch)" | jq -r .status)" "triggered"

  echo
  echo "== 6. a fired watch cannot be cancelled away =="
  expect_status "DELETE on triggered watch" \
    "$(api_status DELETE "/watch-intents/$(watch_id watch)")" 409
  expect_eq "status after refused cancel" \
    "$(api GET "/watch-intents/$(watch_id watch)" | jq -r .status)" "triggered"

  echo
  echo "== 7. an unreachable watch stays active, and cancels normally =="
  cmd_create_watch 400 "" unreachable >/dev/null
  expect_eq "status on create" \
    "$(jq -r .status "${MV_RESULTS}/unreachable.json")" "active"
  expect_eq "no opportunity nested" \
    "$(jq -r '.opportunity == null' "${MV_RESULTS}/unreachable.json")" "true"
  expect_status "DELETE on active watch" \
    "$(api_status DELETE "/watch-intents/$(watch_id unreachable)")" 200

  echo
  echo "== 8. an already-expired watch never fills, even at a reachable price =="
  cmd_create_watch 100 "$(past_timestamp)" expired >/dev/null
  cmd_refresh >/dev/null
  expect_eq "expired watch status" \
    "$(api GET "/watch-intents/$(watch_id expired)" | jq -r .status)" "expired"
  expect_eq "expired watch produced no opportunity" \
    "$(api GET "/opportunities?event_id=${EVENT_ID}" | jq --arg w "$(watch_id expired)" \
        '[.opportunities[] | select(.watch_intent_id == $w)] | length')" "0"

  echo
  echo "== 9. the DB states the invariant: one opportunity per watch =="
  expect_eq "unique constraint present" \
    "$(psql_q -tAc "select conname from pg_constraint where conname = 'uq_opportunities_watch_intent';" | tr -d ' ')" \
    "uq_opportunities_watch_intent"
  expect_eq "old per-book constraint gone" \
    "$(psql_q -tAc "select count(*) from pg_constraint where conname = 'uq_opportunities_identity';" | tr -d ' ')" "0"
  expect_eq "no watch holds more than one opportunity" \
    "$(psql_q -tAc "select count(*) from (select watch_intent_id from opportunities group by watch_intent_id having count(*) > 1) x;" | tr -d ' ')" "0"

  echo
  echo "== 10. 404s still behave =="
  expect_status "GET /watch-intents/does-not-exist" \
    "$(api_status GET /watch-intents/does-not-exist)" 404
  expect_status "GET /opportunities/does-not-exist" \
    "$(api_status GET /opportunities/does-not-exist)" 404

  echo
  echo "== workflow events landed =="
  cmd_events

  echo
  if [[ "$MV_FAILURES" -eq 0 ]]; then
    echo "full run complete: all checks passed"
  else
    echo "full run complete: ${MV_FAILURES} check(s) FAILED"
  fi
  echo "responses saved under ${MV_RESULTS}"
  [[ "$MV_FAILURES" -eq 0 ]]
}

case "${1:-}" in
  up) cmd_up ;;
  down) cmd_down ;;
  reset-db) cmd_reset_db ;;
  clear-watches) cmd_clear_watches ;;
  wait) wait_for_api ;;
  create-watch) shift; cmd_create_watch "$@" ;;
  refresh) cmd_refresh ;;
  watch) shift; cmd_watch "$@" ;;
  opportunities) cmd_opportunities ;;
  opportunity-for) shift; cmd_opportunity_for "$@" ;;
  bump-quote) shift; cmd_bump_quote "$@" ;;
  events) cmd_events ;;
  sql) shift; cmd_sql "$@" ;;
  api) shift; api "$@" ;;
  api-status) shift; api_status "$@" ;;
  watch-id) shift; watch_id "$@" ;;
  past) past_timestamp ;;
  full) cmd_full ;;
  *)
    echo "usage: manual_validation.sh {up|down|reset-db|clear-watches|wait|create-watch|refresh|watch|opportunities|opportunity-for|bump-quote|events|sql|api|api-status|watch-id|past|full}" >&2
    exit 2
    ;;
esac
