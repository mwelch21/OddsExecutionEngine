#!/usr/bin/env bash
# Create a git worktree that can run its own stack alongside the main checkout.
#
# Three things have to line up for two stacks to coexist:
#   1. Distinct container names. Compose derives them from the project name,
#      which defaults to the directory name, so a distinct directory is enough
#      now that docker-compose.yml no longer pins container_name.
#   2. Distinct host ports. That is what the slot below allocates.
#   3. The gitignored files a fresh checkout does not get from git.
#
# Skills are deliberately NOT copied: they live in ~/.agents/skills and resolve
# from any working directory, so every worktree sees them without help.

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

WORKTREE_PARENT="${WORKTREE_PARENT:-$(cd "${ROOT_DIR}/.." && pwd)/$(basename "$ROOT_DIR")-worktrees}"

# Slot 0 belongs to the main checkout. Worktrees start at 1 so a worktree can
# never take the ports the primary checkout expects, even while it is stopped.
FIRST_SLOT=1
MAX_SLOT=20
API_BASE=8000
FRONTEND_BASE=5173
POSTGRES_BASE=5433

usage() {
  cat >&2 <<'USAGE'
usage: scripts/new-worktree.sh <branch> [--from <base>]

  <branch>       branch to create (or check out, if it already exists)
  --from <base>  base to branch from; defaults to origin/development

Creates ../<repo>-worktrees/<branch-slug>, allocates a free port slot, writes
that worktree's .env, and prints the URLs the new stack will listen on.
USAGE
  exit 2
}

[[ $# -ge 1 ]] || usage
BRANCH=""
BASE_REF="origin/development"
while [[ $# -gt 0 ]]; do
  case "$1" in
    --from) [[ $# -ge 2 ]] || usage; BASE_REF="$2"; shift 2 ;;
    -h|--help) usage ;;
    -*) usage ;;
    *) [[ -n "$BRANCH" ]] && usage; BRANCH="$1"; shift ;;
  esac
done
[[ -n "$BRANCH" ]] || usage

# A branch name may contain slashes; a directory name should not.
SLUG="$(printf '%s' "$BRANCH" | tr '/' '-')"
TARGET="${WORKTREE_PARENT}/${SLUG}"

if [[ -e "$TARGET" ]]; then
  printf 'error: %s already exists\n' "$TARGET" >&2
  exit 1
fi

port_in_use() {
  local port="$1"
  if (exec 3<>"/dev/tcp/127.0.0.1/${port}") >/dev/null 2>&1; then
    exec 3<&- 3>&-
    return 0
  fi
  return 1
}

# A slot claimed by a stopped worktree still counts as taken, otherwise two
# worktrees would collide the moment both are running.
claimed_slots() {
  local envfile port
  while read -r envfile; do
    [[ -f "$envfile" ]] || continue
    port="$(grep -E '^APP_PORT=' "$envfile" | tail -1 | cut -d= -f2 | tr -d '[:space:]')"
    [[ "$port" =~ ^[0-9]+$ ]] || continue
    printf '%s\n' "$(( (port - API_BASE) / 100 ))"
  done < <(git worktree list --porcelain | awk '/^worktree /{print $2 "/.env"}')
}

# Space separated rather than an array: macOS ships bash 3.2, which has no
# mapfile, and this script should run under /bin/bash without a Homebrew bash.
CLAIMED="$(claimed_slots | tr '\n' ' ')"

slot_is_free() {
  local slot="$1" claimed
  for claimed in $CLAIMED; do
    [[ "$claimed" == "$slot" ]] && return 1
  done
  port_in_use "$(( API_BASE + slot * 100 ))" && return 1
  port_in_use "$(( FRONTEND_BASE + slot * 100 ))" && return 1
  port_in_use "$(( POSTGRES_BASE + slot * 100 ))" && return 1
  return 0
}

SLOT=""
for candidate in $(seq "$FIRST_SLOT" "$MAX_SLOT"); do
  if slot_is_free "$candidate"; then
    SLOT="$candidate"
    break
  fi
done

if [[ -z "$SLOT" ]]; then
  printf 'error: no free port slot between %s and %s\n' "$FIRST_SLOT" "$MAX_SLOT" >&2
  exit 1
fi

APP_PORT=$(( API_BASE + SLOT * 100 ))
FRONTEND_PORT=$(( FRONTEND_BASE + SLOT * 100 ))
POSTGRES_HOST_PORT=$(( POSTGRES_BASE + SLOT * 100 ))

mkdir -p "$WORKTREE_PARENT"

if git show-ref --verify --quiet "refs/heads/${BRANCH}"; then
  git worktree add "$TARGET" "$BRANCH"
else
  git fetch origin --quiet || true
  git worktree add -b "$BRANCH" "$TARGET" "$BASE_REF"
fi

cat > "${TARGET}/.env" <<ENVFILE
# Written by scripts/new-worktree.sh — port slot ${SLOT}.
# Slot 0 is the main checkout. Each slot adds 100 to every host port so this
# worktree's stack can run at the same time as the others.
APP_PORT=${APP_PORT}
FRONTEND_PORT=${FRONTEND_PORT}
POSTGRES_HOST_PORT=${POSTGRES_HOST_PORT}
ENVFILE

# Claude's per-project permission allowlist is gitignored, so a fresh worktree
# starts with none and re-prompts for everything. Copied rather than symlinked:
# the entries are path-scoped, so the worktree needs its own copy to diverge.
if [[ -f "${ROOT_DIR}/.claude/settings.local.json" ]]; then
  mkdir -p "${TARGET}/.claude"
  cp "${ROOT_DIR}/.claude/settings.local.json" "${TARGET}/.claude/settings.local.json"
fi

cat <<SUMMARY

Worktree ready: ${TARGET}
  branch      ${BRANCH}
  port slot   ${SLOT}
  api         http://localhost:${APP_PORT}
  frontend    http://localhost:${FRONTEND_PORT}
  postgres    localhost:${POSTGRES_HOST_PORT}

Next:
  cd ${TARGET}
  just fresh          # build, migrate, seed
SUMMARY
