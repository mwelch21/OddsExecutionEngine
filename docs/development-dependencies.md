# OddsCafe development dependencies

Target: Ubuntu 24.04 LTS (Noble), amd64, standard EC2 login user with sudo. The checkout name and the Python package still use OddsExecutionEngine. Machine setup uses an explicit package list. Project setup follows the three language manifests.

## Machine inventory

| Dependency | Version or capability | Evidence | Required or optional | Installation method |
|---|---|---|---|---|
| Bash, coreutils, grep, sed, awk, tar, xz, CA certificates | Ubuntu 24.04 base tools | Justfile, worktree and verification scripts, archive installers | Required | Ubuntu base image and apt |
| Git | Worktree and switch support | scripts/new-worktree.sh, README | Required, including before cloning | Ubuntu git |
| curl, jq | TLS, JSON filters | scripts/integration_test.sh, scripts/manual-validation/manual_validation.sh | Required for verification | Ubuntu curl and jq |
| ripgrep, gh | No repo pin | Agent search instructions, docs/agents/issue-tracker.md | Development tools | Ubuntu ripgrep and gh |
| Python | 3.12.x | .python-version, pyproject.toml, CI, Dockerfile | Required | Ubuntu python3 and python3.12 |
| uv | Dependency groups, compatible with revision 3 of uv.lock | CI, Dockerfile, uv.lock | Required | Astral user-local installer |
| Node.js, npm | Node 22.20+ on line 22, 24.12+ on line 24, or ≥25. npm ≥9 handles lock format 3. Fresh installs use line 22. | docker-compose.yml, frontend/package-lock.json, including optional Linux x64 native package | Required for native frontend | Official checksummed Linux archive with bundled npm |
| Go | ≥1.26.1 | services/notifier/go.mod, notifier Dockerfile, Justfile | Required for native notifier builds and tests | Official checksummed Linux archive, latest patch on module's line |
| Docker Engine, Compose CLI plugin, Buildx | Compose up --wait, multi-stage builds | Justfile, Compose files, both Dockerfiles | Required for stack | Ubuntu docker.io, docker-compose-v2, docker-buildx. Existing Docker CE uses its matching plugins. |
| just | Must parse the checked-out Justfile including confirmation attributes | Justfile and README development loop | Optional wrapper, installed for documented commands | Upstream just installer |
| Claude Code, Codex CLI | Working --version, no repo pin | docs/development/worktrees.md, workstation requirements | Developer tools, installed for agent workflow | Claude native installer, npm user prefix for Codex |
| tmux, Runme, golangci-lint | No enforced version | Terminal preference, manual validation suites, ADR-013 | Optional. Current CI runs Python checks only. | Developer-managed |

Ubuntu provides the standard shell utilities. psycopg ships its binary extra, locked Python dependencies have Linux wheels, frontend tooling uses platform packages, and the notifier image builds with CGO disabled. The documented path needs neither a host C/Rust build toolchain nor PostgreSQL development headers. The Go toolchain supplies gofmt, vet and test. Python includes pdb. Vite supplies HMR.

## Project inventory

| Dependency | Locked versions at audit | Evidence | Required or optional | Installation method |
|---|---|---|---|---|
| Backend | Alembic 1.18.4, FastAPI 0.135.3, pydantic-settings 2.13.1, psycopg 3.3.3, SQLAlchemy 2.0.49, Uvicorn 0.44.0 | pyproject.toml and uv.lock | Required | uv sync --locked --group dev (editable backend via Hatchling) |
| Backend dev group | cryptography 46.0.7, httpx 0.28.1, jsonschema 4.26.0, mypy 1.20.0, pytest 8.4.2, pytest-asyncio 1.3.0, Ruff 0.15.10, types-jsonschema 4.26.0.20261006 | pyproject.toml, scripts/generate_vapid_keys.py, backend/tests | Required for full development | Same uv sync |
| Frontend | React and React DOM 18.3.1, lucide-react 0.487.0, Vite 6.4.3, React plugin 4.7.0, TypeScript 5.9.3, React and DOM types 19.3.0 | frontend/package.json, frontend/package-lock.json | Required for UI development | npm ci --include=dev in frontend |
| Go notifier | webpush-go 1.4.0, google/uuid 1.6.0, pgx/v5 5.11.0, jsonschema/v6 6.0.3 | services/notifier/go.mod and go.sum | Required for notifier work | go mod download and go mod verify |
| PostgreSQL, psql, pg_isready | 16 | docker-compose.yml, CI, Justfile | Required for integration | postgres:16 container supplies server and both clients |
| API, auto-refresh, notifier, frontend | Repository source, python:3.12-slim, golang:1.26 builder, distroless Debian 12 runtime, node:22-slim | Dockerfiles, Compose files, frontend/vite.config.ts | API and DB for core. Optional push, automatic refresh and containerized UI. | Compose builds services. just dev runs native Vite. |

The API owns migrations. The Python worker polls PostgreSQL and spends upstream credits only according to operator settings. The Go notifier consumes the PostgreSQL outbox and delivers through browser push services. No separate scheduler, broker or Redis instance is needed. The bootstrap prepares dependencies without starting jobs, applying migrations, seeding fixtures, sending notifications or fetching live odds.

## Configuration and external access

| Scope | Names | Requirement |
|---|---|---|
| Default development | APP_NAME, APP_ENV, APP_HOST, APP_PORT, LOG_LEVEL, FRONTEND_PORT, POSTGRES_HOST_PORT | Optional overrides. The clean checkout uses defaults. |
| PostgreSQL | POSTGRES_DB, POSTGRES_USER, POSTGRES_PASSWORD, POSTGRES_HOST, POSTGRES_PORT | Compose supplies local defaults. Inside Compose use postgres:5432. From the host use localhost and the published port (default 5433). Existing volumes retain their original credentials. |
| Native backend and tests | DATABASE_URL_OVERRIDE, STAGE2_TEST_DATABASE_URL, NOTIFIER_TEST_DATABASE_URL | Optional native DB override. Each test URL is required only for its PostgreSQL-gated suite. Use a dedicated disposable test database. |
| Pricing | QUOTE_PROVIDER, ODDS_API_KEY, ODDS_API_REGIONS, ODDS_API_MARKETS, OPPORTUNITY_TTL_MINUTES, PROVIDER_CACHE_TTL_SECONDS | Defaults work with fixtures. A live The Odds API account and key are required only for odds_api. Refresh calls can spend credits. |
| Push | DATABASE_URL, APP_ORIGIN, VAPID_PUBLIC_KEY, VAPID_PRIVATE_KEY, VAPID_SUBJECT | Compose builds the notifier URL and origin. Full VAPID settings, a browser subscription and a secure browser context enable delivery. Only notifier receives the private key in Compose. |
| Local development routing | FRONTEND_API_TARGET, BASE_URL, FRONTEND_URL, WORKTREE_PARENT, COMPOSE_PROJECT_NAME | Optional Vite proxy, validation URLs, worktree location or Compose isolation. |
| Manual harness | MV_REPO_ROOT, MV_BRANCH_SLUG, MV_SUITE_DIR, MV_RESULTS, EVENT_ID | Suite-specific paths and fixture selections. See scripts/manual-validation/manual_validation.sh. |
| Image build/runtime | PATH, UV_PROJECT_ENVIRONMENT, PYTHONDONTWRITEBYTECODE, PYTHONUNBUFFERED, CGO_ENABLED | Container-specific. Set by Dockerfiles. |
| Developer accounts | GitHub, Claude, OpenAI | Authenticate interactively when using account features. Package downloads use public registries and vendor endpoints. |

There are no required user-supplied secrets for default local development. The templates are public. Doctor reports only presence or connection results. The existing Tailscale, SSH, IAM and Herdr setup is outside machine setup.

## Setup discrepancies found during discovery

- The Python constraint excludes 3.13. Node 22's patch level matters for a locked optional Linux package. The top-level frontend manifest has no engines or packageManager field.
- The backend provider imports httpx at runtime. It currently arrives through the dev group. Pydantic is also imported directly and arrives through declared framework dependencies.
- The API Dockerfile installs uv without a version pin and resolves pyproject.toml without copying uv.lock. Compose frontend and just dev use npm install on startup. Host bootstrap enforces both project locks, while existing container builds and startup commands keep their own resolution behavior.
- React runtime and React type declarations use different major versions. Bootstrap follows the lockfile.
- The notifier requires complete VAPID settings at startup. A fixture-only developer can run just up plus native Vite independently. The full just dev recipe starts the notifier even when its settings are empty.
- Ubuntu's standard Go/Node versions can lag the manifests. PostgreSQL client tools are already in the service image. No host PostgreSQL daemon is installed.
- Deployments, schema changes, external odds subscriptions, cloud resources and push key rotation are separate operator actions.

Installer references: [Ubuntu Docker packages](https://packages.ubuntu.com/search?keywords=docker&suite=noble), [uv installer options](https://docs.astral.sh/uv/reference/installer/), [Node.js releases](https://nodejs.org/dist/), [Go downloads and checksums](https://go.dev/dl/), [just installation](https://just.systems/man/en/packages.html), [Claude Code setup](https://code.claude.com/docs/en/setup), [Codex CLI setup](https://developers.openai.com/codex/cli/).

## Updating dependencies

Use uv add (or uv add --dev), npm install in frontend, or go get and go mod tidy in services/notifier. Commit the matching manifest and lock/checksum files. Rerun bootstrap and doctor. Use scripts/lib/bootstrap-tools.sh for executable/package mappings and version predicates. Add special installers to setup-machine.sh only for requirements apt cannot satisfy. Add a read-only capability check to doctor.sh for new runtimes or services, update this inventory, and test twice on a disposable Noble amd64 machine.
