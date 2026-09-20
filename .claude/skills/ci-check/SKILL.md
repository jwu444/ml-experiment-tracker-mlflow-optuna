---
name: ci-check
description: "Run this project's CI checks (backend make check, frontend type-check/test/build) locally against the current branch or a given PR/branch, without needing GitHub Actions. Use when asked to check CI status, verify a PR is ready to merge, or run CI manually — especially while GitHub Actions is blocked by the account billing/runner-allocation limit (see PR #9). Invoke as `/ci-check` (current branch), `/ci-check <pr-number>`, or `/ci-check <branch-name>`."
---

# ci-check

Replicates what `.github/workflows/ci.yml`'s `backend` and `frontend` jobs
would do, run locally instead of on a GitHub-hosted runner. GitHub Actions is
currently blocked on this repo by an account billing/runner-allocation limit
(jobs queue and get auto-cancelled without ever running — see the PR #9
discussion for the diagnosis); this skill is the manual stand-in until that's
resolved, and doubles as a hands-on way to show what CI actually checks.

Design: `doc/ci-check-skill-design.md`.

**Portability:** every command below assumes cwd is the repo root (confirm
with `git rev-parse --show-toplevel` if unsure). Never hardcode a path tied to
one person's home directory — this skill runs on whoever's machine invokes it,
not just the machine it was written on.

**Trust:** only run this against branches/PRs you trust. `npm ci` (which
executes `package.json`/dependency lifecycle scripts) and `pytest` (via `make
check`) both run code from the checked-out branch on your machine.

## 1. Resolve the target

The skill may be invoked with an argument: `/ci-check`, `/ci-check 9`, or
`/ci-check some-branch-name`.

- **No argument:** operate on whatever branch is currently checked out. Skip
  to step 2.
- **A bare integer** (e.g. `9`): treat it as a PR number.
- **Anything else:** treat it as a branch name.

Before switching branches, always check for uncommitted local work first:

```bash
git status --short
```

If the tree is dirty, **stop and ask** the user how to proceed (stash vs.
commit vs. abort) rather than switching branches over it — never discard
uncommitted work silently.

If the tree is clean, record the starting branch so step 5 can try to return
to it once the checks are done:

```bash
git rev-parse --abbrev-ref HEAD
```

Then switch to the target:

- For a PR number: `gh pr checkout <n>`
- For a branch name: `git checkout <branch>`

If that command fails — `gh` isn't installed/authenticated, or the PR/branch
doesn't exist — **report the failure plainly and stop**. Don't guess at a
target or fall back to whatever happens to be checked out.

Then confirm you're on the expected commit:

```bash
git log -1 --format='%H %s'
```

## 2. Backend check

CI pins Python to **3.12** (`ci.yml`: `python-version: "3.12"`). Verify the
local Poetry venv matches:

```bash
poetry run python --version
```

If it reports anything other than `3.12.x` (a common case: the system default
is 3.13), fix the venv — this mirrors what `actions/setup-python` does in CI,
so it's fair game to fix automatically, unlike the PR's own code:

```bash
pyenv install -s 3.12
poetry env use "$(pyenv root)/versions/$(pyenv versions --bare | grep '^3\.12' | tail -1)/bin/python"
poetry run python --version    # confirm it now reports 3.12.x
```

If `pyenv install` fails (e.g. no network), report that plainly and stop —
don't attempt further workarounds.

CI runs `poetry install --no-interaction` on **every** run, not just when the
Python version needed fixing — do the same here, unconditionally, so a PR
that adds or bumps a backend dependency is checked against a fresh install
rather than a stale local venv (which could otherwise produce a false
`ModuleNotFoundError`-driven FAIL, or mask a real one):

```bash
poetry install
```

Then run the same command CI runs:

```bash
make check
```

`make check` is `lint + format-check + type-check + test` (ruff, black
--check, mypy strict, pytest) — record whether it exits clean. This is the
full result for the `backend` job.

## 3. Frontend check

CI pins Node to **`"22"`** (`ci.yml`: `actions/setup-node@v4` with
`node-version: "22"`). This skill does not auto-fix the Node version the way
it does for Python above — that's out of scope — but check it and report any
mismatch as an environment note:

```bash
node --version
```

CI's `frontend` job runs `npm ci` first — which requires a **committed**
`frontend/package-lock.json`. Before running it, confirm the lockfile is
actually committed on this branch — not just that a file with that name
happens to exist on disk:

```bash
git cat-file -e HEAD:frontend/package-lock.json
```

Exit code `0` means the file exists in the commit at `HEAD` on this branch.
Any non-zero exit means it doesn't — either because it was never added at
all, or because it's only staged (`git add`ed) but never committed. That
second case is the one to watch for: a check against the git *index* (e.g.
`git ls-files`, or a plain `git status`) would report the file as present the
moment someone runs `git add frontend/package-lock.json`, even though nothing
has been committed and a fresh CI checkout would still have no lockfile.
`git cat-file -e HEAD:<path>` looks at the committed tree, not the index, so
it isn't fooled by that in-between state — exactly the state a student is
likely in seconds after fixing PR #9's bug and running this skill to check
their own fix, before they've committed it.

This check matters for a second reason too: your local working directory is
*not* a fresh CI checkout. A prior `npm install`/`npm ci` run — in an earlier
session, on a different branch, maybe done specifically to work around this
exact `npm ci` failure — can leave an **untracked, gitignored**
`package-lock.json` (and a matching `node_modules/`) sitting in `frontend/`.
`git checkout`/`gh pr checkout` never touch untracked files, so that leftover
silently survives across branches and sessions. Skip this check and jump
straight to `npm ci`, and a stale local lockfile can make it **spuriously
succeed** — masking the real failure a genuine CI runner (which always
starts from `actions/checkout@v4`, i.e. zero leftover state) would hit.

- **Command exits non-zero (not committed):** this alone is decisive. A
  fresh CI checkout has no `package-lock.json` at all unless it's committed,
  so `npm ci` *will* fail there regardless of what currently sits in your
  local `frontend/`. Report `frontend` FAIL at `npm ci` (lockfile not
  committed) now — do not run `npm ci` against the polluted local state and
  trust a pass. `type-check`/`test`/`build` are correctly *not* attempted,
  same as a real CI run would do. (Real CI would actually fail one step
  earlier than `npm ci`: its `actions/setup-node@v4` step is configured with
  `cache-dependency-path: frontend/package-lock.json` and hard-errors trying
  to hash a file that doesn't exist, before `npm ci` ever runs. Same root
  cause — no committed lockfile — just a more precise step name if you want
  to match CI's exact failure point.)
  - Optional, only if you want to demonstrate the actual failure locally
    (e.g. for a report): temporarily move the stale files aside, run
    `npm ci` for real, then put them back so you don't leave a working
    local dev environment broken:
    ```bash
    stash="$(mktemp -d)"
    mv frontend/package-lock.json frontend/node_modules "$stash/"
    (cd frontend && npm ci)   # now fails for real, matching CI
    mv "$stash/package-lock.json" "$stash/node_modules" frontend/
    ```
- **Committed:** proceed and run it exactly as CI does:
  ```bash
  cd frontend && npm ci
  ```

**If `npm ci` exits non-zero for any reason — missing/uncommitted lockfile,
lockfile out of sync with `package.json`, a dependency conflict, a
registry/network error, or anything else — that is a failure of the
`frontend` job.** The cause only changes the one-line detail in the report;
it never changes whether it's a FAIL. Do not fall back to `npm install` to
"get past it" and keep checking type-check/test/build; that would hide the
exact class of bug already found on PR #9 (a workflow that requires `npm ci`
while `.gitignore` excludes `package-lock.json`). Stop the frontend check
here and note in the report that `type-check`/`test`/`build` were not run
because `npm ci` itself failed — that's what a real CI run would do too.

If `npm ci` succeeds — and the lockfile was genuinely committed, not just
present on disk — continue with the rest of CI's `frontend` job. Keep cwd
unambiguous (running these from the repo root instead of `frontend/` fails
on a missing `package.json`, which would get misreported as a `frontend` bug
in the PR when it's really just a cwd mistake):

```bash
npm --prefix frontend run type-check
npm --prefix frontend test
npm --prefix frontend run build
```

Record pass/fail for each.

## 4. Drift check

`.github/workflows/ci.yml` doesn't exist on `main` (or on this branch) at
all — as of this writing it lives only on PR #9's branch,
`phase1/task-1-github-actions-ci`, which is still unmerged. If it's missing
from the target branch when you run this: say so plainly in the report — the
backend/frontend steps in §2/§3 above were transcribed from that PR #9
version, not read live off a file on the branch being checked. Run the
checks anyway (they're still the best available approximation of real CI);
just note that the drift check itself couldn't be performed against a live
`ci.yml` this run.

If `.github/workflows/ci.yml` *does* exist on the target branch (e.g. once
PR #9 merges), read it and compare it against the steps above:

- Does it still pin Python 3.12 and Node the same way?
- Are `make check` and the four npm commands above still exactly what the
  `backend`/`frontend` jobs run, in the same order?
- Has a step been added or removed in the workflow that this skill doesn't
  cover (e.g. a new service container, a new lint step, a matrix build)?

If you notice a mismatch, call it out explicitly in the report below — don't
silently keep using stale steps. This is a judgment call each run, not a
mechanical diff.

## 5. Report

Before summarizing, try to return to the branch recorded in step 1: if
`git status --short` is still clean (the checks above shouldn't have
modified tracked files) and the checkout succeeds, run
`git checkout <starting-branch>`. If the tree isn't clean, or the checkout
fails, stay put rather than forcing it — either way, note in the report
which branch things ended on.

Summarize using the same two names GitHub's own status checks use, so the
output reads the way a real CI run would:

```
backend:   <PASS/FAIL> — <one-line detail if FAIL>
frontend:  <PASS/FAIL> — <one-line detail if FAIL, and which step it failed at>
ended on:  <branch> — restored to starting branch / stayed on target branch (reason)
```

For each failure, say whether it's an **environment issue** (e.g. wrong
Python version — already auto-fixed above, so this shouldn't reach the
report) or a **genuine code/config gap in the branch/PR** (e.g. missing
lockfile, a failing test, a type error) — the two categories call for
different next actions from whoever's reading the report.

If step 4 found drift between this skill and `ci.yml`, add a short note about
it after the summary.
