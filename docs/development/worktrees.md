# Running two stacks at once

Two git worktrees of this repo can bring up their Docker stacks concurrently, so
a backend branch and a frontend branch can be worked in parallel instead of
serially.

## Create one

```bash
./scripts/new-worktree.sh feature/my-branch
# or, with just installed:
just worktree feature/my-branch
```

The worktree lands in `../OddsExecutionEngine-worktrees/<branch-slug>`, branched
from `origin/development` (override with `--from <ref>`). The script prints the
URLs its stack will use. Then:

```bash
cd ../OddsExecutionEngine-worktrees/feature-my-branch
just fresh
```

## What made this impossible before

Three things, all now fixed:

**Container names were pinned.** `docker-compose.yml` set `container_name` on
every service, which overrides the per-project namespacing Compose applies by
default. A second stack collided on name. The pins are gone; Compose derives
container names from the project name, which defaults to the directory name, so
distinct worktree directories are enough.

**Host ports were hardcoded.** A second stack collided on port. Every published
port now reads from the environment.

**Scratch state did not travel.** A fresh worktree got none of the gitignored
files. Most of that problem dissolved when skills moved to `~/.agents/skills`,
which resolves from any working directory. What remains is copied by the script.

## Port slots

A slot shifts every host port by `slot * 100`. Slot 0 is the main checkout and
is never assigned to a worktree — so a worktree cannot take the primary
checkout's ports even while that stack is stopped.

| | api | frontend | postgres |
|---|---|---|---|
| slot 0 (main checkout) | 8000 | 5173 | 5433 |
| slot 1 | 8100 | 5273 | 5533 |
| slot 2 | 8200 | 5373 | 5633 |

`scripts/new-worktree.sh` allocates the first free slot and writes it to the new
worktree's `.env`. Free means two things: no other worktree has claimed the slot
in its own `.env`, **and** all three ports are currently unbound. Checking only
live ports would hand out a slot already claimed by a stopped worktree, and the
collision would appear later, when both happened to be running.

A checkout with no `.env` gets slot 0 from the defaults in `docker-compose.yml`,
so nothing about the single-stack workflow changed.

## Databases are already isolated

Each worktree is a separate Compose project, so each gets its own volume. There
is no shared database to coordinate — but it does mean every worktree migrates
and seeds independently. `just fresh` does both.

## Scripts target their own stack

`scripts/lib/stack-env.sh` resolves `BASE_URL` from the worktree's `.env`, and
`scripts/verify_stage2_5.sh`, `scripts/integration_test.sh` and the manual
validation harness all read through it.

This matters more than it sounds. Before, running a verification script from
worktree B would validate worktree A's stack on `:8000` and report green. A
false pass is worse than a collision, because a collision is loud.

## Skills are not copied

Skills live in `~/.agents/skills/`, symlinked into `~/.claude/skills/`. Codex
reads `~/.agents/skills/` directly. They resolve from any working directory, so
every worktree sees them with no carry-over step.

The only thing the script copies is `.claude/settings.local.json`, Claude's
per-project permission allowlist — copied rather than symlinked because its
entries are path-scoped and each worktree should be free to diverge.

## Cleaning up

```bash
cd ../OddsExecutionEngine-worktrees/feature-my-branch
just down-hard          # stop the stack and delete its volume
cd -
git worktree remove ../OddsExecutionEngine-worktrees/feature-my-branch
```

`git worktree list` shows what exists. A worktree removed by hand without
`git worktree remove` leaves a stale entry; `git worktree prune` clears it.
