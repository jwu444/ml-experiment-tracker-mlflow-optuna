# Project 1 — Week 3–4 Infra Enhancement

**Goal:** during the Week 3–4 enhancement phase, introduce commonly used commercial/professional tools into Project 1 so the student gets hands-on exposure to how real teams build, test, and ship — not just as an add-on, but attached to gaps the codebase already has.

**Tracking issues:** [#16 LangSmith](https://github.com/jwu444/WavePoint-Project-1/issues/16) · [#17 Render + Vercel](https://github.com/jwu444/WavePoint-Project-1/issues/17) · [#18 GitHub Actions CI](https://github.com/jwu444/WavePoint-Project-1/issues/18) · [#19 Cloudflare R2](https://github.com/jwu444/WavePoint-Project-1/issues/19) — all labeled `infra enhancement`.

## Why these four, why now

The current codebase has concrete gaps that this phase's own goals already call for filling:

- `Makefile`'s `eval` target is a literal stub (`@echo "Eval suite arrives in a later plan (make eval)"`), and Week 3's goal is exactly to build a 30+ pair golden Q/A eval harness.
- There is no `.github/` directory — `make check` (ruff + black + mypy strict + pytest) exists but nothing runs it automatically on a PR.
- Nothing is deployed yet — `.env.example` anticipates a production Postgres `DATABASE_URL`, but the only thing running today is local SQLite, and Week 4's goal is to deploy and demo.
- Uploaded CSVs are stored as an inline `Text` blob in the `datasets.data_csv` Postgres column (`backend/app/models.py`) and read straight back into pandas (`backend/app/dataset_io.py`) — a real anti-pattern that only works because files are small today.

Rather than hand-build all four from scratch, each is filled with the commercial tool a professional team would actually reach for.

## The three tools

### 1. LangSmith — tracing + eval harness (issue #16)
All Claude calls already funnel through one file, `backend/app/llm.py`, which makes this a clean single integration point. LangSmith gives automatic tracing (input/output/latency/token/cost per call) plus a hosted eval framework to run the golden Q/A set against, replacing the hand-rolled pass/fail script `make eval` currently lacks. This is also the exact observability tool Project 2 is already planned to use — starting it in Project 1 means Project 2 forks a repo that's already instrumented instead of adding this cold in week 5.

### 2. Render (backend + Postgres) + Vercel (frontend) — deployment (issue #17)
Splitting frontend/backend across two managed hosts is the standard industry pattern, not a hypothetical. Render gives one-click managed Postgres next to the FastAPI service with no Dockerfile required; Vercel gives free automatic preview deployments on every PR, which is a genuinely useful professional workflow moment for the student to see working.

### 3. GitHub Actions — CI gate (issue #18)
`make check` already exists and runs clean locally; wiring it to run on every push/PR is close to zero new work since the checks are already written. This is the most basic professional-engineering habit currently missing from the repo.

### 4. Cloudflare R2 — object storage for uploaded CSVs (issue #19)
S3-compatible API (same client code path as real AWS S3), free tier with no credit card, no egress fees. Replaces the inline `Text` blob in `datasets.data_csv` with an object key referencing the file in R2 — the standard way uploaded files are handled in production, and a lower-friction on-ramp to object storage than provisioning real AWS.

**Why not BigQuery here too:** BigQuery is a data-warehouse/OLAP tool for querying large structured datasets — Project 1 is small, single-user CSVs processed in-memory with pandas, so there's no motivating gap to hang it on. It's already correctly scheduled in `doc/tools-platforms.md` as a Tier B sandbox session in Weeks 9–10 (Project 3), once the student is working with a larger domain dataset. Pulling it into Project 1 now would break the "grounded in an actual gap" rule the other four items follow.

## Sequencing across weeks 3–4

1. **Week 3:** #16 (LangSmith) — pairs directly with the golden Q/A eval work already planned for this week. #18 (CI) can be added in parallel since it's low-effort and unblocks safely running everything else.
2. **Week 4:** #19 (R2 storage migration) before #17 (Render + Vercel deploy) — cleaner to migrate storage before standing up the production DB, so the deployed environment starts correct rather than needing a follow-up migration. Deploying is the natural "harden and ship" close to the phase.

## Out of scope / stretch (not opened as issues yet)

- **Neon** as the managed Postgres instead of Render's built-in one — same one-click simplicity, but it's the same pgvector-capable Postgres story Project 2 needs, so the DB wouldn't have to migrate later. Worth a follow-up issue if there's time.
- **Sentry** — ~10 lines to wire up, catches real production exceptions (bad CSVs, Claude timeouts) with stack traces. Low effort, but not tied to an existing stated goal this phase, so left for a later pass.
- **BigQuery** — deliberately deferred to Weeks 9–10 / Project 3 per `doc/tools-platforms.md`; see rationale above.
