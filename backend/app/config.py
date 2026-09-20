import json
from typing import Annotated

from pydantic import field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "sqlite:///./dev.db"
    max_upload_bytes: int = 50 * 1024 * 1024  # 50 MB
    max_rows: int = 1_000_000
    # Frontend CORS (prod only; dev uses the Vite /api proxy). Override via .env or a
    # host's dashboard as a bare origin, a comma-separated list, or a JSON list.
    # NoDecode + the validator below are what make the first two legal: without them
    # pydantic-settings JSON-decodes any list-typed env var BEFORE validation, so a
    # plainly-typed `https://app.example.com` raises SettingsError at import and the
    # process cannot boot. On a host that keeps the previous instance alive when a
    # deploy fails its health check, that surfaces as the old container serving 200s
    # with the DEFAULT origins — the setting silently not taking, with the deploy
    # looking healthy from outside. Observed on Render, Task 14.
    cors_allow_origins: Annotated[list[str], NoDecode] = ["http://localhost:5173"]

    @field_validator("cors_allow_origins", mode="before")
    @classmethod
    def _parse_origins(cls, value: object) -> object:
        """A JSON list stays a JSON list; anything else splits on commas."""
        if not isinstance(value, str):
            return value
        text = value.strip()
        if text.startswith("["):
            return json.loads(text)
        return [part.strip() for part in text.split(",") if part.strip()]

    # Profiler tunables (design §4) — single source of truth; override per-env via .env.
    profile_max_cardinality: int = 20  # value_counts only for non-numeric cols at/below this; top-N
    profile_max_corr_cols: int = 30  # full correlation matrix up to this many numeric cols
    profile_top_corr_pairs: int = 25  # beyond the col cap, keep only the strongest N pairs
    profile_sample_rows: int = 5  # sample rows included in the profile
    profile_token_budget: int = 8000  # approx token ceiling for the assembled profile

    # Training (Project 2 §3.6). Seeded so a re-run of the same experiment
    # reproduces the same metrics — otherwise MLflow history is not comparable.
    train_test_size: float = 0.2
    train_test_seed: int = 42
    cv_folds: int = 5
    # Categorical columns above this many distinct values are treated as
    # identifiers, not features (§3.3).
    feature_max_cardinality: int = 20

    # Optuna (design §3.8). Bounded so a runaway search space cannot hang the
    # endpoint — studies are synchronous by design. These two are the whole
    # budget: a trial count the route rejects above, and a wall-clock cap on the
    # study. There is deliberately no per-trial timeout — Optuna's `timeout=`
    # bounds the study, not a trial, and interrupting one CPU-bound
    # `cross_val_score` would need a subprocess pool with hard termination
    # (threads cannot be force-killed in Python). That is not worth building for
    # the current registry's search spaces at this data size; revisit if a slow
    # model type is added.
    optuna_max_trials: int = 50
    optuna_study_timeout_s: int = 600

    # Anthropic (required for /chat; key never hardcoded)
    anthropic_api_key: str = ""
    anthropic_model: str = "claude-sonnet-5"
    anthropic_max_tokens: int = 4096

    # MLflow (design D4). The tracking store shares the app's Postgres in its own
    # `mlflow` schema — no second database to provision. Artifacts (models, plots)
    # stay on local disk; MLflow's own UI is never publicly hosted (D10), because
    # run browsing lives in the app's own ExperimentsPage (D9).
    mlflow_tracking_uri: str = ""
    mlflow_artifact_root: str = "./mlruns"

    # LLM loop (issue #9). A turn runs up to llm_max_passes analyst passes; a
    # separate judge scores each 0-100 and the loop stops at >= threshold or the
    # cap, returning the best-scoring pass. judge_model="" reuses anthropic_model.
    llm_max_passes: int = 3
    llm_quality_threshold: int = 80
    judge_model: str = ""

    # OpenTelemetry (3.1). Off by default: `make test` must need no collector and
    # CI no service container. docker-compose already runs Jaeger with OTLP on
    # 4318 and its UI on 16686 — this is what finally sends it anything.
    otel_enabled: bool = False
    otel_exporter_otlp_endpoint: str = "http://localhost:4318"

    # Voyage embeddings (D14, 3.3). 512 dimensions via Matryoshka truncation, to
    # match EMBEDDING_DIM — the column already exists at that width, so a
    # different output dimension would cost a migration rather than a config
    # change. The key is needed by `make embed` AND, once the agent lands, at
    # request time, because every agent search embeds its query.
    #
    # D14 fixes the provider and the width, never the model string. The plan
    # named voyage-3.5; by the time this was written that had become the previous
    # generation, and voyage-4 supports the same 512-dimension output. Changing
    # it later is not free — every indexed vector has to be recomputed, because
    # two models' vectors are not comparable — so it is settled here, while the
    # index is still empty.
    voyage_api_key: str = ""
    voyage_model: str = "voyage-4"

    # Voyage's free tier allows 3 requests/minute. `make embed` embeds one
    # document per changed source, so a review session of a dozen notes trips
    # that limit as a matter of course, and an unretried 429 aborts the backfill
    # partway — leaving the index half-reconciled, which is the state 3.3b's
    # reap exists to prevent. Retries are bounded and exponential; a key that is
    # genuinely over quota fails after `voyage_max_attempts` rather than hanging.
    voyage_max_attempts: int = 4
    voyage_retry_base_seconds: float = 2.0

    # Chunking (D29, 3.3). A configuration value because Phase 4's sweep needs
    # to vary it (D46) — but changing it is NOT a cheap config change: every
    # indexed vector has to be recomputed, so `make embed` must be re-run.
    chunk_max_chars: int = 1000

    # Retrieval (3.4). `retrieval_top_k` counts SOURCES, not chunks: a k of
    # chunks lets one four-chunk finding fill the whole budget and hide three
    # other runs, and the agent then answers from one source while sounding
    # comprehensive. `chunk_overfetch` is the multiplier applied before grouping,
    # so k sources survive the collapse.
    retrieval_top_k: int = 8
    chunk_overfetch: int = 4

    # The agent's tool-loop bound (3.5). Hitting it does NOT end the request
    # empty-handed: the loop makes one further call with the tools removed, and
    # that call is not counted — a model that spent its budget searching would
    # otherwise return nothing, which reads as a backend failure.
    agent_max_turns: int = 6

    # The ceiling on the `k` the model may ask search_runs for. Every returned
    # source's snippet is packed into the tool result and therefore into the
    # model's context, and stage 2 over-fetches `k * chunk_overfetch` chunks from
    # pgvector to get there — so an unbounded k is a way for one tool call to
    # blow the context window and the request's cost. Rejected as a message the
    # model can act on, not clamped silently: a k of 500 answered with 25 sources
    # looks to the model like the history only holds 25.
    agent_max_k: int = 25

    # Ceiling on the rows get_leaderboard will return. Rejected, not clamped —
    # same rule as agent_max_k: answering a request for 500 rows with 20 tells
    # the model the investigation holds 20, and it then reports that.
    agent_max_leaderboard_rows: int = 20


settings = Settings()
