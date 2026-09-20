# Deploy runbook — Render + Cloudflare R2

How this app was actually deployed, in the order it was done, with the values
that worked and the three things that did not. It is written to be repeatable:
a second deploy follows the same steps, and the failures recorded here are the
ones that cost time the first time.

The shape is §7.1's: a **static site** for the SPA, a **Docker web service** for
the API, and one **Postgres** holding both the `app` schema and MLflow's
`mlflow` schema (D4). Artifacts live in **Cloudflare R2** (D48) — not on the
service's disk, which Render's free tier wipes on every deploy.

Everything below is on Render's free tier. See [Free-tier
caveats](#free-tier-caveats) for what that costs.

---

## Step 1 — the Blueprint

`render.yaml` at the repo root declares all three. In Render: **New → Blueprint**,
pick the repo, pick the branch. Render reads the manifest from **that branch**,
not from `main`; the branch is changeable afterwards per service, in Settings.

Both services inherit the Blueprint's branch because neither declares a
`branch:` key. That is deliberate — one place to change it.

Two manifest errors that reject the **entire** blueprint, so nothing at all gets
created:

1. **`type: static` does not exist.** A static site is `type: web` with
   `runtime: static`. Render's schema has no `static` type.
2. **`preDeployCommand` is not supported on free-tier services.** The MLflow
   migration that used to live there now runs in `docker-entrypoint.sh`, before
   `exec uvicorn` — see [Step 3](#step-3--prepare-the-mlflow-store).

`backend/tests/test_deploy_config.py` pins both, plus the health-check path and
`npm ci`. It did not catch the first one when it shipped: the tests selected
services by `type == "static"`, the same wrong assumption the manifest made, so
they could not fail on it. They now select on `runtime`.

## Step 2 — secrets

Every `sync: false` variable in `render.yaml` is declared but valueless; a human
types it into the dashboard. On **wavepoint-api**:

| Variable | Value |
| --- | --- |
| `ANTHROPIC_API_KEY` | your key |
| `VOYAGE_API_KEY` | your key |
| `MLFLOW_ARTIFACT_ROOT` | `s3://wavepoint-artifacts/mlruns` |
| `MLFLOW_S3_ENDPOINT_URL` | `https://<account-id>.r2.cloudflarestorage.com` |
| `AWS_ACCESS_KEY_ID` | the R2 access key |
| `AWS_SECRET_ACCESS_KEY` | the R2 secret |
| `CORS_ALLOW_ORIGINS` | the static site's URL (see below) |

`DATABASE_URL` and `MLFLOW_TRACKING_URI` are **not** typed by hand — both bind
to the database through `fromDatabase: {name: wavepoint-db}`, by name, which is
why the database must be the one the Blueprint created rather than one made
separately in the dashboard. Use the **internal** connection string for
anything running inside Render; the external one is for your laptop.

> **`CORS_ALLOW_ORIGINS` and `VITE_API_BASE` reference each other's service**,
> so neither can be filled in until both have deployed once and have URLs. Set
> them after Step 4, and expect the first deploy of each to be wrong.

### The CORS variable will boot-loop a stricter build

`Settings.cors_allow_origins` is list-typed. pydantic-settings JSON-decodes
list-typed env vars **before** validation, so a plainly-typed
`https://wavepoint-web.onrender.com` used to raise `SettingsError` at import —
uvicorn never bound, the health check failed, and **Render kept the previous
container serving**. The visible result was a healthy-looking site whose API
answered `200` using the *default* origins, with the new setting silently not
applied. The field now accepts a bare origin, a comma-separated list, or a JSON
list, so all three of these are legal:

```
CORS_ALLOW_ORIGINS=https://wavepoint-web.onrender.com
CORS_ALLOW_ORIGINS=https://a.example.com,https://b.example.com
CORS_ALLOW_ORIGINS='["https://wavepoint-web.onrender.com"]'
```

To check it took, ask the API for the header directly — a `200` alone proves
nothing:

```bash
curl -s -D - -o /dev/null -H "Origin: https://wavepoint-web.onrender.com" \
  https://wavepoint-api.onrender.com/datasets | grep -i access-control
```

Getting `access-control-allow-origin: http://localhost:5173` back means the
service is running the code default and your value did not reach it.

## Step 3 — prepare the MLflow store

Nothing to do by hand: `docker-entrypoint.sh` runs
`scripts/prepare_mlflow_store.py` and then `exec uvicorn`, in that order, so the
store is migrated before the server binds. The script does two things the plain
`mlflow db upgrade` does not:

- `CREATE SCHEMA IF NOT EXISTS mlflow`, over the **raw** URI. A connection
  already pinned to a schema cannot create it.
- appends `?options=-csearch_path=mlflow` to the URI it prints, which the
  entrypoint exports as `MLFLOW_TRACKING_URI`. Without it MLflow builds its ~59
  tables in `public` and the app reads an empty store while everything reports
  success.

`mlflow db upgrade` is idempotent Alembic, and the free tier runs a single
instance with no overlap between old and new containers, so running it at every
container start is safe.

## Step 4 — the two cross-referencing URLs

Once both services have deployed once and have URLs:

- on **wavepoint-api**: `CORS_ALLOW_ORIGINS` = the static site's URL
- on **wavepoint-web**: `VITE_API_BASE` = the API's URL

`VITE_API_BASE` is inlined by Vite **at build time**, so setting it does nothing
until the static site rebuilds. Confirm it landed by grepping the served bundle,
not the dashboard:

```bash
JS=$(curl -s https://wavepoint-web.onrender.com/ | grep -o '/assets/[^"]*\.js' | head -1)
curl -s "https://wavepoint-web.onrender.com$JS" | grep -c wavepoint-api.onrender.com
```

Unset, the bundle falls back to the relative `/api`, which resolves against the
static site's own origin, where the `/*` rewrite answers every API call with
`index.html` and a `200`: no error, no data.

## Step 5 — move the data

The app is deployed but empty. Two transfers, in this order.

### 5a — the database

Dump both schemas from the local dev Postgres and restore into Render's.

```bash
pg_dump --schema=app --schema=mlflow \
  "postgresql://wavepoint:wavepoint@localhost:5433/wavepoint" > /tmp/wavepoint.sql
```

**The dump is not self-sufficient**, in two ways:

1. It references `public.vector(512)` but contains **no `CREATE EXTENSION`** —
   pgvector lives in `public`, which `--schema=app --schema=mlflow` excludes. In
   practice Render's database already had it, because deploying the API ran
   `init_db()`'s `alembic upgrade head` and our own initial migration creates the
   extension. Do not rely on that; `CREATE EXTENSION IF NOT EXISTS vector;`
   costs nothing.
2. **The target is not empty.** By the time you restore, the API has already
   created both schemas — 69 tables — via `alembic upgrade head` and
   `mlflow db upgrade`. The dump's `CREATE SCHEMA app;` collides.

So the restore drops first. Do it as **one** `psql` invocation, not three: the
free tier sleeps, and a wake between the drop and the restore lets the API
recreate the schemas in the gap.

```bash
psql -v ON_ERROR_STOP=1 "$RENDER_EXTERNAL_URL" <<'SQL'
DROP SCHEMA IF EXISTS app CASCADE;
DROP SCHEMA IF EXISTS mlflow CASCADE;
CREATE EXTENSION IF NOT EXISTS vector;
SQL
psql -v ON_ERROR_STOP=1 "$RENDER_EXTERNAL_URL" -f /tmp/wavepoint.sql
```

Before dropping anything, confirm the target really is a fresh deploy and not
data: every table should be empty except MLflow's own `alembic_version` and
`workspaces`.

Verify by comparing table counts and per-table row counts on both sides. The
first deploy landed **69 tables and zero row-count mismatches**.

> In zsh, `cmd | tail` reports **tail's** exit status, and the array is
> `$pipestatus`, not `PIPESTATUS`. A restore that failed can easily look like it
> succeeded. Compare row counts rather than trusting an exit code.

### 5b — rewrite the artifact URIs

The restored rows still point at the laptop that trained them. `make embed`-style
reconciliation does not cover this; `scripts/migrate_artifact_uris.py` does. It
is **dry-run by default** — inspect the plan, then re-run with `--apply`.

```bash
poetry run python scripts/migrate_artifact_uris.py \
  --database-url "$RENDER_EXTERNAL_URL" \
  --old-root "/Users/justinwu/dev/wavepoint/wavepoint-project-2/mlruns" \
  --new-root "s3://wavepoint-artifacts/mlruns" \
  --apply
```

**`--old-root` is a bare absolute path with no `file://` scheme** — that is what
MLflow stored, and a `file://`-prefixed value matches nothing and rewrites zero
rows while exiting successfully. Confirm the value first:

```bash
psql "$LOCAL_URL" -tAc "select distinct artifact_location from mlflow.experiments;"
```

It rewrites **three** columns, and the third is the one that matters:

| Table | Column | Rows, first deploy |
| --- | --- | --- |
| `mlflow.experiments` | `artifact_location` | 7 |
| `mlflow.runs` | `artifact_uri` | 36 |
| `mlflow.logged_models` | `artifact_location` | 36 |

`runs:/{run_id}/model` — what `POST /runs/{id}/diagnostics` loads — resolves
through **`logged_models.artifact_location`** in MLflow 3.x, not through
`runs.artifact_uri`. Rewriting only the first two leaves every model unreachable
while every row looks migrated. Total: **79 rows**; the post-check found `s3=79`
and local-path `0` across all three columns.

Two of 36 models then failed to load. Both were rows whose artifacts were
**already missing on the laptop** (34 of 36 present) — pre-existing local rot
carried across faithfully, not a migration defect. Behaviour is unchanged from
local, so they were left alone.

## Step 6 — smoke test

Run these against the live deploy. Items 6 and 7 are the load-bearing pair: they
prove R2 works in **both** directions, which nothing else does.

| # | Check | First deploy |
| --- | --- | --- |
| 1 | `GET /health` → 200 | ✅ 0.26s warm |
| 2 | SPA nav rail lists datasets **and** experiments | ✅ needs Step 4 |
| 3 | Leaderboard ranks, with cv bands and `within_noise` | ✅ 26 rows, `mlflow_available=true` |
| 4 | `GET /findings` returns the approved corpus | ✅ 6 (3 eda + 3 diagnostic) |
| 5 | `POST /agent/chat` cites sources, each deep-linking (3.6b) | ✅ 8 sources, 12s, $0.0509 |
| 6 | `POST /runs/{id}/diagnostics` → 201 draft finding | ✅ 119s — **reads a model out of R2** |
| 7 | `POST /experiments/{id}/train` → 200 | ✅ r²=0.977 — **writes a new one back** |
| 8 | Re-upload an identical CSV → 200, same id, no new row (#7) | ✅ count still 3 |

Item 2 is two independent fetches on purpose: one list failing must not blank
the other. Item 5's citations must be *clicked*, not just counted — a citation
you cannot click through is unfalsifiable (3.6b).

Note on the indexed corpus: it is **21 sources** (17 note + 3 diagnostic + 1
eda), not 23. All three EDA findings belong to one dataset and correctly
concatenate under a single `("eda", dataset_id)` key (3.3b). Adding 3 + 17 + 3
double-counts them.

Items 6 and 7 leave real rows behind — one draft diagnostic finding and one
run labelled as a smoke test. They are the evidence; deleting them deletes the
proof.

## Free-tier caveats

- **Services sleep after ~15 minutes of inactivity.** The first request wakes
  the container and takes **≈50 seconds**. Nothing is wrong; it is cold.
- **The free Postgres expires after ~30 days.** It is deleted, not downgraded.
  Re-running Step 5 against a fresh database is the recovery, which is the other
  reason this runbook exists.
- **No shell access**, which is why the MLflow migration lives in the container
  entrypoint rather than in a command you could run by hand.
- **Tracing stays off** (`OTEL_ENABLED=false` in `render.yaml`). No collector is
  deployed and Jaeger stays a local tool (§7.4). `app/tracing.py` works
  regardless — OpenTelemetry's default tracer returns a non-recording span, so
  no caller branches on whether tracing is on.
