#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
source scripts/lib/bootstrap-tools.sh
trap 'echo "Project setup failed at line $LINENO. Check the manifest, lockfile and registry access, then rerun." >&2' ERR

uv sync --locked --group dev --python "$python_series"
(cd frontend && npm ci --include=dev)
(cd services/notifier && go mod download && go mod verify)
# Atomically publish the public template, including on concurrent first runs.
if [[ ! -e .env && ! -L .env ]]; then
    template=$(mktemp .env.bootstrap.XXXXXX)
    trap 'rm -f -- "$template"' EXIT
    cat .env.example > "$template"
    ln -T "$template" .env || [[ -f .env ]]
fi
[[ -f .env ]] || { echo 'Expected .env to be a regular file.' >&2; exit 1; }
