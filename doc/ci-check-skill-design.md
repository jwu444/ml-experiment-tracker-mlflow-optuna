# `ci-check` — a Claude Code skill to run CI checks manually

**Status:** approved — 2026-08-07
**Issue:** #11 — *Add a Claude Code skill to simulate the CI pipeline locally (ci-check)*
**Scope:** a single project-scoped Claude Code skill. No git hook, no shared shell
script, no install step — that automation was considered and deliberately dropped
(see §6).

## 1. Problem

GitHub Actions is currently blocked on this private repo by an account
billing/runner-allocation limit: pushed jobs queue for ~15 minutes waiting for a
hosted runner, never get one assigned, and are auto-cancelled without executing a
step (`duration_ms: 0` for both jobs — see PR #9). We've decided not to spend
money to raise that limit right now.

In the meantime, `backend`/`frontend` checks still need to be run by hand against
a PR — and doing that from memory risks drifting from what
`.github/workflows/ci.yml` actually specifies. On PR #9 a manual run caught a real
bug (`npm ci` needs a committed `frontend/package-lock.json`, which `.gitignore`
excludes) that a vaguer "run `make check` and `npm test`" habit would have missed.

The purpose of `ci-check` is as much pedagogical as practical: it gives the
student a concrete, inspectable stand-in for "what does CI actually do," runnable
on demand, without needing GitHub Actions minutes.

## 2. Design

A single Claude Code skill, `.claude/skills/ci-check/SKILL.md`, **committed to
this repo** (not a personal/global skill) so it ships with the project and is
available in any Claude Code session opened here — the student's included.

**Portability constraint.** This skill runs on the student's machine, not just
the instructor's — every path or command in `SKILL.md` and every command Claude
runs on its behalf must be relative to the repo root (e.g. derived from
`git rev-parse --show-toplevel`, or simply run with cwd already at the repo
root, matching how the existing `Makefile` targets behave). No absolute path
tied to one person's home directory (`/Users/<name>/...`, `/home/<name>/...`,
etc.) may appear in the skill's instructions or in anything it writes.

**Invocation:** `/ci-check [pr-number-or-branch]`

- No argument → operate on whatever branch is currently checked out.
- A bare integer (e.g. `/ci-check 9`) → treated as a PR number: `gh pr checkout
  <n>` first, after the normal git-safety check for uncommitted local work
  (never discard it — stash or ask).
- Anything else → treated as a branch name: `git checkout <branch>` under the
  same safety rule.

**What it does, in order:**

1. **Resolve target** per the invocation rule above.
2. **Backend.** Verify the Poetry venv is Python 3.12 (matching `ci.yml`'s
   `python-version: "3.12"` pin). If it's on a different version (e.g. the
   system's 3.13), fix it: `pyenv install -s 3.12`, `poetry env use`, then
   `poetry install`. This mirrors what `actions/setup-python` does in CI, so
   correcting it is "faithfully running CI," not touching the PR's own code —
   auto-fixing it is in scope. Then run `make check`.
3. **Frontend.** Before running `npm ci`, gate on a `git`-tracked-tree check
   (`git cat-file -e HEAD:frontend/package-lock.json`) — not just `npm ci`'s
   own exit code — to confirm the lockfile is actually committed, not merely
   present (or staged) in the local working copy. This guards against local
   environment contamination: a stray untracked or staged-but-uncommitted
   lockfile left over from an earlier session could otherwise make `npm ci`
   spuriously pass against state a fresh CI checkout would never have. Then
   run `npm ci` exactly as CI does. If it fails for any reason — lockfile not
   committed, out of sync with `package.json`, or otherwise — **report that as
   a finding** — do not silently fall back to `npm install`. That failure is a
   real gap in the PR's committed files, not a local environment quirk, and
   papering over it would hide the exact class of bug found on PR #9. If
   `npm ci` succeeds, continue with `npm run type-check`, `npm test`,
   `npm run build`.
4. **Drift check.** Read `.github/workflows/ci.yml` and compare its steps
   against what was just run; flag anything the workflow does that this skill
   doesn't cover, or vice versa (e.g. a Node/Python version bump, a new step).
   This is the "keeps up with `ci.yml`" guarantee — a human noticing at run
   time, not generic YAML execution.
5. **Report.** A clear pass/fail per job, using the same `backend` / `frontend`
   names GitHub's own status checks use, so the output reads the same way a real
   CI run would. Each failure names what broke and, if it's a known category
   (env version mismatch vs. a genuine code/config gap), says which.

## 3. Error handling

- **Uncommitted local work.** Before any `git checkout`/`gh pr checkout`, check
  `git status`; if the tree is dirty, stop and ask rather than switching
  branches over it (standard git-safety practice, not special-cased logic).
- **`gh` unavailable/unauthenticated, or PR/branch not found.** Report clearly
  and stop — don't guess at a target.
- **Environment fix fails** (e.g. `pyenv install` fails offline). Report the
  failure plainly; don't attempt further workarounds silently.

## 4. Out of scope (revisit later if it's worth it)

- **Any automatic trigger** (pre-push git hook, post-commit hook, etc.). Initial
  brainstorm proposed a pre-push hook calling a shared shell script that both the
  hook and this skill would invoke. Deliberately dropped: the purpose of this
  tool right now is to show the student the concept of CI hands-on through the
  skill itself, not to build automation infrastructure around it. A shared
  script, an installer, and hook wiring are all real added surface area with no
  clear payoff yet.
- **Fully dynamic YAML-driven execution** (parsing `ci.yml` and deriving/running
  steps generically instead of the explicit steps in §2). Considered and
  rejected: `ci.yml` is two simple jobs today, and GitHub Actions constructs
  (`actions/setup-python`, service containers, etc.) don't always have a clean
  local equivalent — the complexity isn't justified yet. The §2 step-4 drift
  check gets most of the safety of this without the fragility.
- **Bit-for-bit runner parity** (e.g. via `act`/Docker). The goal is fast,
  good-enough local verification, not exact GitHub Actions environment
  replication.
- **Actually resolving the GitHub Actions billing/runner-allocation problem.**
  Separate decision, tracked by the discussion on PR #9, not by this skill.

## 5. Acceptance check

Running `/ci-check 9` should reproduce the manual run already validated by hand:
backend fully green (ruff, black, mypy strict, all tests), frontend green through
`type-check`/`test`/`build`, but `npm ci` reported as a failure due to the missing
`frontend/package-lock.json`.
