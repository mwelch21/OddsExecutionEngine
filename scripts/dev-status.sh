#!/usr/bin/env bash
# Is the running local stack in step with the checked-out branch?
#
# Read-only: inspects git, Docker and the database, changes nothing. Run via
# `just status`. Every check says what to run when it fails, and the script
# exits non-zero when any check does, so it can gate other tooling.
set -uo pipefail

cd "$(dirname "$0")/.."

stale=0
warn() {
    echo "$1  [STALE]"
    stale=1
}

echo "branch   $(git branch --show-current) @ $(git rev-parse --short HEAD)"
echo

container="$(docker compose ps -q api 2>/dev/null)"
if [[ -z "$container" ]]; then
    echo "api      not running -> just refresh"
    exit 1
fi

docker compose ps --format 'table {{.Service}}\t{{.State}}\t{{.Ports}}'
echo

# Reload mode: the dev override replaces the image's command with one carrying
# --reload. Without it, backend edits are invisible until the next rebuild.
if docker inspect -f '{{join .Config.Cmd " "}}' "$container" | grep -q -- '--reload'; then
    echo "reload   on   (backend edits apply on save)"
else
    warn "reload   off  (image mode: backend edits need a rebuild) -> just refresh"
fi

# Dependencies are baked into the image, not mounted. The image keeps the
# pyproject.toml it was built from, so compare contents: mtimes would flag a
# file that was merely touched, which a cached rebuild never clears.
if docker compose exec -T api cat /app/pyproject.toml 2>/dev/null | cmp -s - pyproject.toml; then
    echo "image    built from this pyproject.toml"
else
    warn "image    built from a different pyproject.toml -> just refresh"
fi

# Schema: the database should sit at the newest migration on this branch.
alembic=(docker compose exec -T api uv run alembic -c backend/db/alembic.ini)
current="$("${alembic[@]}" current 2>/dev/null | awk '/^[0-9a-z_]+/{print $1}')"
head="$("${alembic[@]}" heads 2>/dev/null | awk '/^[0-9a-z_]+/{print $1}')"
if [[ -n "$head" && "$current" == "$head" ]]; then
    echo "schema   at head ($head)"
else
    warn "schema   ${current:-none} != head ${head:-unknown} -> just migrate"
fi

echo
if [[ "$stale" -eq 0 ]]; then
    echo "stack matches this checkout"
else
    echo "stack is stale; run the commands above"
fi
exit "$stale"
