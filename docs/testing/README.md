# Testing Strategy

## Test Layers

| Layer | Tool | What it covers | When to run |
|-------|------|----------------|-------------|
| Unit | `uv run pytest` | Engines, events, domain logic | Every change |
| SQLite smoke | `uv run pytest` | API endpoints, persistence adapters (lightweight) | Every change |
| Postgres truth | `uv run pytest` (with `STAGE2_TEST_DATABASE_URL`) | Full persistence correctness against real Postgres | CI + before merge |
| Integration script | `scripts/integration_test.sh` | End-to-end against Docker stack: all endpoints, DB state, tracing | Before merge, manual |
| Testing UI | `GET /test-ui` (dev only) | Manual exploration of all endpoints with pre-built scenarios | During development |

## Running Tests

### Unit + SQLite smoke (fast, no Docker needed)

```bash
uv run pytest
```

### Linting + type checking

```bash
uv run ruff check .
uv run mypy backend
```

### Full integration (requires Docker)

```bash
# Run all integration tests, clean up containers after
./scripts/integration_test.sh --cleanup

# Skip rebuild if containers already running
./scripts/integration_test.sh --skip-build
```

### Testing UI

Start the stack, then visit `http://localhost:8000/test-ui` in a browser.

```bash
docker compose up --build -d
docker compose exec -T api uv run alembic -c backend/db/alembic.ini upgrade head
docker compose exec -T api uv run odds-db-seed-demo
# open http://localhost:8000/test-ui
```

The UI is only available when `APP_ENV=development` (the default). It returns 404 in production.

## Fixture Data

The canonical test fixture is defined in `backend/app/infrastructure/quote_provider.py:build_fixture_quotes()`.

| Field | Value |
|-------|-------|
| Event ID | `nba-knicks-celtics-2026-04-11` |
| Sportsbooks | BetMGM, DraftKings, FanDuel, Caesars |
| Markets | 3 moneyline, 3 spread (2 at 5.5, 1 at 4.5), 3 total (2 over, 1 under at 221.5), 1 celtics moneyline |
| Total quotes | 10 |

When adding new fixture data for future stages, update `build_fixture_quotes()` and adjust expected counts in:
- `backend/tests/test_app.py` (SQLite integration tests)
- `scripts/integration_test.sh` (database state assertions)
- Testing UI `SCENARIOS` in `backend/app/api/test_ui_router.py`

## Adding Tests for New Stages

Checklist when shipping a new stage:

1. **Unit tests** - add test file in `backend/tests/` for new engines or domain logic
2. **SQLite smoke tests** - add endpoint tests in `test_app.py` using `_build_test_app` helper
3. **Integration script** - add a test group in `scripts/integration_test.sh`:
   - Add test functions following the `test_*()` pattern
   - Wire them with `run_test "description" test_function_name`
   - Update DB state assertions if new tables or row counts change
4. **Testing UI** - add scenario entry to the `SCENARIOS` array in `backend/app/api/test_ui_router.py`
5. **Postgres truth test** - if the feature has persistence, add a Postgres-gated test (skipped without `STAGE2_TEST_DATABASE_URL`)

## Integration Script Reference

`scripts/integration_test.sh` flags:

| Flag | Effect |
|------|--------|
| `--cleanup` | Run `docker compose down -v` after tests |
| `--skip-build` | Skip `--build` on `docker compose up` (faster if already built) |

Exit code: 0 if all tests pass, 1 if any fail.

Adding a new test group:
1. Add a `test_*()` function
2. Call it with `run_test "Human-readable name" test_function_name`
3. Use helpers: `assert_json`, `assert_equals`, `assert_gte`, `post_json`, `get_status`, `query_count`

## Testing UI Maintenance

The dashboard is a single HTML file returned by `backend/app/api/test_ui_router.py`. All CSS/JS is inline.

To add a new scenario:
1. Add an entry to the `SCENARIOS` JavaScript array
2. Set `key`, `label`, `desc`, `method`, `endpoint`, `body`
3. For expected-failure scenarios, prefix `key` with `validation-` so "Run All" expects 422

The UI is gated by `app_env == "development"` in `backend/app/main.py`. The router is lazily imported.

## CI

Automated tests run on pull requests to `development` via `.github/workflows/tests-before-merge.yml`:
- Ruff lint
- Mypy type check
- Pytest (with Postgres service for integration tests)

The integration script (`scripts/integration_test.sh`) is not part of CI. It is intended for local pre-merge verification against the full Docker stack.
