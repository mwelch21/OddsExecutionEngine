#!/usr/bin/env bash
# Diagnostics only. No install, login, migrations, refreshes or service starts.
set -uo pipefail
cd "$(dirname "$0")/.."
source scripts/lib/bootstrap-tools.sh
failures=0
pass() { printf 'PASS  %s\n' "$*"; }
warn() { printf 'WARN  %s\n' "$*"; }
fail() { printf 'FAIL  %s\n' "$*"; failures=1; }

version() {
    local label=$1 description
    shift
    if description=$("$@" 2>/dev/null); then
        pass "$label  ${description%%$'\n'*}"
    else
        fail "$label unavailable. Run ./scripts/setup-machine.sh."
    fi
}
if [[ -r /etc/os-release ]] && (
    source /etc/os-release
    [[ $ID == ubuntu && $VERSION_ID == 24.04 && $(uname -m) == x86_64 ]]
); then
    pass 'Ubuntu 24.04 x86_64'
else
    warn 'Machine installer targets Ubuntu 24.04 x86_64.'
fi
for entry in "${machine_tools[@]}"; do
    exe=${entry%:*}
    version "$exe" "$exe" --version
done
if uv_ok 2>/dev/null; then version uv uv --version; else fail 'Install current uv via setup-machine.sh.'; fi
if node_ok 2>/dev/null; then
    version Node node --version
    version npm npm --version
else
    fail 'Install compatible Node and npm via setup-machine.sh (Node 22.20+ on line 22, npm 9+).'
fi
if go_ok 2>/dev/null; then version Go env GOTOOLCHAIN=local go version
else fail "Install Go $go_min or newer via setup-machine.sh."; fi
if just_ok 2>/dev/null; then version just just --version; else fail 'Install just with Justfile support via setup-machine.sh.'; fi
version Claude claude --version
version Codex codex --version

py=.venv/bin/python
if "$py" -IB -c 'import sys; assert ".".join(map(str,sys.version_info[:2])) == sys.argv[1]' "$python_series" 2>/dev/null; then
    version 'Project Python' "$py" --version
else
    fail "Project needs Python $python_series. Run setup-project.sh."
fi
if "$py" -IB - 2>/dev/null <<'PY'
import importlib.metadata as meta
import tomllib
from pathlib import Path
from packaging.requirements import Requirement

project = tomllib.loads(Path("pyproject.toml").read_text())
lock = tomllib.loads(Path("uv.lock").read_text())
versions = {p["name"]: p["version"] for p in lock["package"]}
for spec in project["project"]["dependencies"] + project["dependency-groups"]["dev"]:
    req = Requirement(spec)
    if not req.marker or req.marker.evaluate():
        assert meta.version(req.name) == versions[req.name.lower()]
import fastapi, httpx, psycopg, sqlalchemy, uvicorn
PY
then pass 'Backend runtime and dev packages match locked direct dependencies.'
else fail 'Backend environment incomplete or stale. Run setup-project.sh.'; fi

if (cd frontend && node --input-type=commonjs - 2>/dev/null <<'JS'
const fs = require("node:fs");
const manifest = require("./package.json");
const lock = require("./package-lock.json").packages;
for (const group of ["dependencies", "devDependencies"]) {
    for (const [name, range] of Object.entries(manifest[group])) {
        const path = "node_modules/" + name;
        const installed = JSON.parse(fs.readFileSync(path + "/package.json"));
        if (installed.version !== lock[path].version || range !== lock[""][group][name]) process.exit(1);
    }
}
JS
); then pass 'Frontend runtime and dev packages match lockfile.'
else fail 'Frontend environment incomplete or stale. Run setup-project.sh.'; fi

# Let the application's dotenv parser resolve settings. Report status only.
if [[ -f .env ]]; then pass 'Project .env present.'; else warn 'Run setup-project.sh to create .env from the public template.'; fi
if [[ -x $py ]]; then
    config_flags=$(PYTHONDONTWRITEBYTECODE=1 "$py" - 2>/dev/null <<'PY'
import os
from dotenv import dotenv_values
from backend.app.config import Settings
file_env = dotenv_values(".env")
s = Settings()
print("missing-key" if s.quote_provider == "odds_api" and not s.odds_api_key.strip() else "provider-ok")
print("push-ready" if all(os.getenv(k, file_env.get(k)) for k in ("VAPID_PUBLIC_KEY", "VAPID_PRIVATE_KEY", "VAPID_SUBJECT")) else "push-incomplete")
if s.database_url_override or s.postgres_host != "postgres":
    import psycopg
    from sqlalchemy.engine import make_url
    url = make_url(s.database_url).set(drivername="postgresql")
    with psycopg.connect(url.render_as_string(hide_password=False), connect_timeout=4) as conn:
        conn.execute("SELECT 1").fetchone()
    print("native-db-ok")
PY
)
    if (( $? )); then fail 'Check application settings, POSTGRES_HOST/PORT and any DATABASE_URL_OVERRIDE.'
    else
        if [[ $config_flags == *missing-key* ]]; then fail 'Live odds selected. Set ODDS_API_KEY in .env.'
        else pass 'Provider configuration present.'; fi
        if [[ $config_flags == *push-ready* ]]; then pass 'Web Push settings present.'
        else warn 'Web Push disabled or incomplete. See docs/runbooks/web-push.md to enable the notifier.'; fi
        if [[ $config_flags == *native-db-ok* ]]; then pass 'Configured database answered SELECT 1.'; fi
    fi
fi

version Docker docker --version
version Buildx docker buildx version
if compose_ok 2>/dev/null; then version Compose docker compose version
else fail 'Install Docker Compose plugin with up --wait support.'; fi
if docker info >/dev/null 2>&1; then
    pass 'Docker daemon accessible.'
    if running=$(docker compose ps --services --status running 2>/dev/null) &&
        restarting=$(docker compose ps --services --status restarting 2>/dev/null); then
        for service in postgres api auto-refresh notifier frontend; do
            if grep -Fxq "$service" <<< "$running"; then
                pass "$service running."
            elif grep -Fxq "$service" <<< "$restarting" &&
                [[ $service != notifier || ${config_flags:-} == *push-ready* ]]; then
                fail "$service is restarting. Check docker compose logs $service."
            elif [[ $service == frontend ]]; then
                warn 'Frontend container stopped. just dev serves Vite on the host.'
            else
                warn "$service stopped. Use just up for core services or just dev for the full stack."
            fi
        done
        if grep -Fxq postgres <<< "$running"; then
            if docker compose exec -T postgres sh -c 'PGCONNECT_TIMEOUT=4 PGPASSWORD="$POSTGRES_PASSWORD" psql -X -w -h 127.0.0.1 -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Atqc "SELECT 1"' >/dev/null 2>&1; then
                pass 'Compose PostgreSQL answered SELECT 1.'
            else fail 'PostgreSQL login failed. Check database settings against the initialized volume.'; fi
        fi
        if grep -Fxq api <<< "$running"; then
            if docker compose exec -T api python -Bc 'import json,urllib.request; assert json.load(urllib.request.urlopen("http://localhost:8000/api/health",timeout=4))["database"]=="healthy"' >/dev/null 2>&1; then
                pass 'API health endpoint reports healthy database.'
            else fail 'API health failed. Check docker compose logs api.'; fi
        fi
    else fail 'Cannot inspect this Compose project. Check docker compose config --quiet.'; fi
else fail 'Docker daemon inaccessible. Reconnect SSH for docker group access and check systemctl status docker.'; fi
exit "$failures"
