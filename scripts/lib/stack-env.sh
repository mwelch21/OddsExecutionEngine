# Resolves which stack this checkout talks to. Source it, do not execute it.
#
# Ports are per-worktree: scripts/new-worktree.sh writes a slot into the new
# worktree's .env. Without that file we fall back to slot 0, the values this
# repo has always used.
#
# This matters more than it looks. Before ports were configurable, running a
# verification script from worktree B would happily validate worktree A's stack
# on :8000 and report green — a false pass, which is worse than a collision.

_stack_env_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"

if [[ -f "${_stack_env_root}/.env" ]]; then
  # Only KEY=VALUE lines; ignore comments and anything malformed rather than
  # eval-ing whatever happens to be in the file.
  while IFS='=' read -r _key _value; do
    [[ "$_key" =~ ^[A-Z_][A-Z0-9_]*$ ]] || continue
    # Existing environment wins, so an explicit override still works.
    [[ -n "${!_key:-}" ]] && continue
    export "$_key=$_value"
  done < <(grep -E '^[A-Z_][A-Z0-9_]*=' "${_stack_env_root}/.env" || true)
fi

export APP_PORT="${APP_PORT:-8000}"
export FRONTEND_PORT="${FRONTEND_PORT:-5173}"
export POSTGRES_HOST_PORT="${POSTGRES_HOST_PORT:-5433}"
export BASE_URL="${BASE_URL:-http://localhost:${APP_PORT}}"
export FRONTEND_URL="${FRONTEND_URL:-http://localhost:${FRONTEND_PORT}}"
