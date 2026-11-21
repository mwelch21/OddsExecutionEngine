#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
./scripts/setup-machine.sh
./scripts/setup-project.sh
if ! docker info >/dev/null 2>&1 && id -nG "$(id -un)" | tr ' ' '\n' | grep -Fxq docker; then
    echo 'Starting diagnostics with Docker group access. Reconnect SSH before running just dev.'
    exec sg docker -c './scripts/doctor.sh'
fi
exec ./scripts/doctor.sh
