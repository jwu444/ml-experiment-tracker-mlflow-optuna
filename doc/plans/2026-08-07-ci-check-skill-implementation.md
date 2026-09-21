# `ci-check` Skill Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship `.claude/skills/ci-check/SKILL.md`, a project-committed Claude Code
skill that replicates `.github/workflows/ci.yml`'s `backend` and `frontend` jobs
locally, on demand, against the current branch or a given PR/branch.

**Architecture:** A single instructions file, no code, no dependencies, no
install step. It travels with the repo (`.claude/skills/ci-check/`) so it's
available in any Claude Code session opened here. Verification is an actual
end-to-end run against a real PR, not a unit test — there's no code to unit test.

**Tech Stack:** Markdown + YAML frontmatter (the skill file itself); the checks
it drives are the project's existing `make check` (Poetry/ruff/black/mypy/pytest)
and npm scripts (`ci`/`type-check`/`test`/`build`).

## Global Constraints

- Design: `doc/ci-check-skill-design.md`. Read it before starting — every
  section below implements one part of it.
- **Portability.** Nothing in the skill file may hardcode a path tied to one
  person's home directory (`/Users/<name>/...`, `/home/<name>/...`). Every
  command assumes cwd is the repo root (obtainable via
  `git rev-parse --show-toplevel`).
- **Scope.** This is the skill only — no git hook, no shared shell script, no
  installer. That automation was explicitly considered and dropped (design §4).
- **`npm ci` failures are findings, not obstacles.** If the frontend check's
  `npm ci` step fails (e.g. missing `frontend/package-lock.json`, the exact bug
  found on PR #9), the skill must report that as the `frontend` job's failure
  and stop — never silently substitute `npm install` to push further.
- **Git safety.** Never switch branches over uncommitted local work; check
  `git status --short` first and stop to ask if the tree is dirty.

---

### Task 1: Write the `ci-check` skill file

**Files:**
- Create: `.claude/skills/ci-check/SKILL.md`

**Interfaces:**
- Consumes: nothing (first task).
- Produces: `.claude/skills/ci-check/SKILL.md` with YAML frontmatter
  (`name: ci-check`, `description: ...`) and five body sections — `## 1.
  Resolve the target`, `## 2. Backend check`, `## 3. Frontend check`, `## 4.
  Drift check`, `## 5. Report` — that Task 2 invokes end-to-end.

- [x] **Step 1: Create the directory and write the frontmatter + intro**

```bash
mkdir -p .claude/skills/ci-check
```

Create `.claude/skills/ci-check/SKILL.md` with this content (frontmatter +
intro + portability note only — later steps append the rest):

```markdown
---
name: ci-check
description: Run this project's CI checks (backend make check, frontend type-check/test/build) locally against the current branch or a given PR/branch, without needing GitHub Actions. Use when asked to check CI status, verify a PR is ready to merge, or run CI manually — especially while GitHub Actions is blocked by the account billing/runner-allocation limit (see PR #9). Invoke as `/ci-check` (current branch), `/ci-check <pr-number>`, or `/ci-check <branch-name>`.
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
```

**Note:** the `description:` field above is unquoted, which is the exact bug
fixed in commit `a794c57` (an unquoted `#9)` mid-string starts a YAML comment
and truncates the description). This embedded example is left as-written for
historical accuracy — see `.claude/skills/ci-check/SKILL.md` for the current
(quoted) frontmatter. Do not copy this block verbatim.

- [x] **Step 2: Verify the frontmatter is valid YAML**

```bash
python3 -c "
import yaml
text = open('.claude/skills/ci-check/SKILL.md').read()
front = text.split('---')[1]
d = yaml.safe_load(front)
assert d['name'] == 'ci-check'
assert 'description' in d and len(d['description']) > 0
print('frontmatter ok:', d['name'])
"
```

Expected: `frontmatter ok: ci-check`.

- [x] **Step 3: Append the "Resolve the target" section**

Append to `.claude/skills/ci-check/SKILL.md`:

```markdown

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

If the tree is clean:

- For a PR number: `gh pr checkout <n>`
- For a branch name: `git checkout <branch>`

If that command fails — `gh` isn't installed/authenticated, or the PR/branch
doesn't exist — **report the failure plainly and stop**. Don't guess at a
target or fall back to whatever happens to be checked out.

Then confirm you're on the expected commit:

```bash
git log -1 --format='%H %s'
```
```

- [x] **Step 4: Append the "Backend check" section**

Append to `.claude/skills/ci-check/SKILL.md`:

```markdown

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
poetry install
poetry run python --version    # confirm it now reports 3.12.x
```

If `pyenv install` fails (e.g. no network), report that plainly and stop —
don't attempt further workarounds.

Then run the same command CI runs:

```bash
make check
```

`make check` is `lint + format-check + type-check + test` (ruff, black
--check, mypy strict, pytest) — record whether it exits clean. This is the
full result for the `backend` job.
```

- [x] **Step 5: Append the "Frontend check" section**

Append to `.claude/skills/ci-check/SKILL.md`:

```markdown

## 3. Frontend check

CI's `frontend` job runs `npm ci` first — which requires a **committed**
`frontend/package-lock.json`. Run it exactly as CI does:

```bash
cd frontend && npm ci
```

**If `npm ci` fails because the lockfile is missing or out of date, that is a
genuine finding — report it as a failure of the `frontend` job.** Do not fall
back to `npm install` to "get past it" and keep checking
type-check/test/build; that would hide the exact class of bug already found
on PR #9 (a workflow that requires `npm ci` while `.gitignore` excludes
`package-lock.json`). Stop the frontend check here and note in the report
that `type-check`/`test`/`build` were not run because `npm ci` itself
failed — that's what a real CI run would do too.

If `npm ci` succeeds, continue with the rest of CI's `frontend` job, in
order:

```bash
npm run type-check
npm test
npm run build
```

Record pass/fail for each.
```

**Note:** superseded by commit `36ecb91` (which replaced the plain
`cd frontend && npm ci` with a trackedness check ahead of it, first written
as `git -C frontend ls-files --error-unmatch package-lock.json`), and now
further revised by the final-review fix wave (Fixes 1, 2, 4, 8, 9 — see
`doc/ci-check-skill-design.md` and the fix report under
`.superpowers/sdd/2026-08-07-ci-check-skill-implementation/`). See
`.claude/skills/ci-check/SKILL.md` §3 for the current content; do not
re-execute this embedded block verbatim.

- [x] **Step 6: Append the "Drift check" and "Report" sections**

Append to `.claude/skills/ci-check/SKILL.md`:

```markdown

## 4. Drift check

Read `.github/workflows/ci.yml` and compare it against the steps above:

- Does it still pin Python 3.12 and Node the same way?
- Are `make check` and the four npm commands above still exactly what the
  `backend`/`frontend` jobs run, in the same order?
- Has a step been added or removed in the workflow that this skill doesn't
  cover (e.g. a new service container, a new lint step, a matrix build)?

If you notice a mismatch, call it out explicitly in the report below — don't
silently keep using stale steps. This is a judgment call each run, not a
mechanical diff.

## 5. Report

Summarize using the same two names GitHub's own status checks use, so the
output reads the way a real CI run would:

```
backend:   <PASS/FAIL> — <one-line detail if FAIL>
frontend:  <PASS/FAIL> — <one-line detail if FAIL, and which step it failed at>
```

For each failure, say whether it's an **environment issue** (e.g. wrong
Python version — already auto-fixed above, so this shouldn't reach the
report) or a **genuine code/config gap in the branch/PR** (e.g. missing
lockfile, a failing test, a type error) — the two categories call for
different next actions from whoever's reading the report.

If step 4 found drift between this skill and `ci.yml`, add a short note about
it after the summary.
```

- [x] **Step 7: Self-review against the design doc**

Read `.claude/skills/ci-check/SKILL.md` end to end and check it against
`doc/ci-check-skill-design.md` §2–§5:

- All five numbered steps present, in order, matching the design's intent.
- The portability constraint (design §2) is stated near the top.
- The `npm ci`-failure-is-a-finding rule (design §3, and Global Constraints
  above) is unambiguous — an implementer reading only this file, with no
  memory of the design discussion, must not be able to read it as "fall back
  to `npm install`."
- No absolute path anywhere in the file:

```bash
grep -n "/Users/\|/home/" .claude/skills/ci-check/SKILL.md
```

Expected: no output. If anything is missing or ambiguous, fix it now before
committing.

- [x] **Step 8: Commit**

```bash
git add .claude/skills/ci-check/SKILL.md
git commit -m "feat: add the ci-check skill (issue #11)

Replicates ci.yml's backend/frontend jobs locally on demand, while
GitHub Actions is blocked by the account billing/runner limit (PR #9).
A missing/stale frontend lockfile is reported as a frontend-job
failure, never silently worked around."
```

---

### Task 2: Acceptance run against PR #9

**Files:**
- None expected — this task only modifies `.claude/skills/ci-check/SKILL.md`
  if the run below surfaces a bug in Task 1's content.

**Interfaces:**
- Consumes: the `ci-check` skill from Task 1, invoked (or, if not yet
  discoverable this session, read and manually followed) against PR #9 in
  `jwu444/ml-experiment-tracker-mlflow-optuna`.
- Produces: a verified skill file, confirmed to reproduce the manual result
  already established for PR #9.

- [x] **Step 1: Try invoking the skill directly**

In this same session, attempt:

```
Skill(skill="ci-check", args="9")
```

A newly created project skill may not appear in the session's already-loaded
skill listing (that listing is captured at session start). If the tool call
errors because `ci-check` isn't recognized, that's expected — proceed to
Step 2 instead of treating it as a failure of Task 1's content.

- [x] **Step 2: Fallback — walk through the file's instructions directly**

If Step 1 wasn't invocable, open `.claude/skills/ci-check/SKILL.md` and
execute its five sections by hand, exactly as written, with target `9` (PR
number). This validates the file's actual content just as rigorously as a
live slash-invocation would — the difference is only *how* the instructions
get run, not *what* gets checked.

- [x] **Step 3: Compare the result against the known-good manual run**

The design doc's acceptance check (§5) and this project's own earlier manual
verification of PR #9 established:

- `backend` — fully green: ruff clean, black clean, mypy strict clean, all
  108 tests pass (after fixing the Poetry venv to Python 3.12).
- `frontend` — `npm run type-check` clean, `npm test` 74/74 pass, `npm run
  build` succeeds *when run directly*, but **`npm ci` fails** because
  `frontend/package-lock.json` does not exist, since `.gitignore` excludes it
  while `ci.yml` requires a committed lockfile.

Confirm the skill's run (Step 1 or 2) reaches the same conclusion: `backend`
reported PASS, `frontend` reported FAIL specifically at the `npm ci` step,
with `type-check`/`test`/`build` correctly *not* attempted per the Task 1
Step 5 rule.

- [x] **Step 4: Fix and re-run if it doesn't match**

If the skill's actual behavior diverges from Step 3's expected result (e.g.
it silently falls back to `npm install`, or mis-categorizes the failure),
edit `.claude/skills/ci-check/SKILL.md` to close the gap, then repeat Steps
1–3.

- [x] **Step 5: Commit if Step 4 required changes**

Skip this step if Task 1's file needed no fixes.

```bash
git add .claude/skills/ci-check/SKILL.md
git commit -m "fix: correct ci-check behavior found during PR #9 acceptance run"
```

- [x] **Step 6: Note the discoverability caveat for next session**

If Step 1 wasn't invocable (fell back to Step 2), say so plainly in the
final report to the user: the skill's *content* is verified, but a live
`/ci-check` smoke test — confirming the harness actually offers/invokes it
by name — is still worth doing in a fresh Claude Code session opened on this
repo.

---

## Acceptance criteria (from `doc/ci-check-skill-design.md` §5)

- `.claude/skills/ci-check/SKILL.md` exists, is committed, and has valid
  frontmatter.
- No absolute/machine-specific path appears anywhere in the file.
- Running it (live or by manual walkthrough) against PR #9 reports `backend`
  PASS and `frontend` FAIL-at-`npm ci`, matching the already-validated manual
  result.
- A missing/stale lockfile is never silently papered over with `npm install`.
