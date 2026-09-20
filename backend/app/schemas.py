import datetime as dt
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class DatasetOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str
    n_rows: int
    n_cols: int


class DatasetColumnOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    name: str
    inferred_type: str
    null_count: int


class DatasetDetailOut(DatasetOut):
    """The detail route only. `GET /datasets` stays on `DatasetOut` — the list
    is rendered as a nav sidebar, and paying for every dataset's full column
    list on every load buys nothing it displays."""

    columns: list[DatasetColumnOut]


class HyperparamSpecOut(BaseModel):
    """One `ModelSpec.search_space` entry, flattened out of its tuple."""

    name: str
    type: str
    min: float
    max: float
    log_scale: bool


class ModelSpecOut(BaseModel):
    model_type: str
    task_type: str
    tunable: bool
    hyperparams: list[HyperparamSpecOut]
    # Hyperparameters whose value is one of the dataset's column names. Empty
    # for every model but the persistence baseline; a form renders a column
    # picker for each, rather than knowing that model by name (#51).
    column_hyperparams: list[str]


class ChatCreateRequest(BaseModel):
    dataset_ids: list[str]


class ChatDatasetOut(BaseModel):
    id: str
    name: str


class ChatOut(BaseModel):
    id: str
    datasets: list[ChatDatasetOut]


class ChatRequest(BaseModel):
    question: str


class AnalystPassOut(BaseModel):
    model: str
    tokens_in: int
    tokens_out: int
    latency_ms: int
    cost_usd: float
    interpretation: str


class JudgePassOut(BaseModel):
    model: str
    tokens_in: int
    tokens_out: int
    latency_ms: int
    cost_usd: float
    score: int | None
    feedback: str
    gaps: list[str]


class PassTraceOut(BaseModel):
    pass_no: int
    analyst: AnalystPassOut
    charts: list[str]
    stats: list[dict[str, Any]]
    errors: list[str]
    judge: JudgePassOut
    revision_instruction: str


class MessageTraceOut(BaseModel):
    # Per-pass records only. The system prompt is intentionally excluded — it can
    # leak guardrail language, so it never leaves the backend.
    passes: list[PassTraceOut]


class ChatMessageOut(BaseModel):
    id: str
    role: str
    content: str
    charts: list[str] = []
    stats: list[dict[str, Any]] = []
    errors: list[str] = []
    # Per-pass loop trace (issue #9 review); None for user rows and pre-trace rows.
    trace: MessageTraceOut | None = None


class ChatHistoryOut(BaseModel):
    datasets: list[ChatDatasetOut]
    messages: list[ChatMessageOut]


# Pydantic v2 reserves the `model_` prefix for its own attributes, so a field
# named `model_type` emits a protected-namespace warning unless the namespace is
# cleared. Every schema below carries a model_type, so every one clears it.
_ML = ConfigDict(protected_namespaces=())


class TrainRequest(BaseModel):
    """dataset_id, target_column and task_type are NOT here — they are inherited
    from the parent experiment (D34/D35). Launching under
    `/experiments/{id}/train` is what supplies them.
    """

    model_config = _ML

    model_type: str
    hyperparams: dict[str, Any] = Field(default_factory=dict)
    feature_columns: list[str] | None = None
    # Naming a time column switches the whole run to a chronological split
    # (§3.6). Omitting it on a temporal dataset is how leakage gets in, so the
    # route rejects an unknown name rather than silently falling back.
    time_column: str | None = None
    notes: str = ""


class RunOut(BaseModel):
    model_config = _ML

    run_id: str
    mlflow_run_id: str
    status: str
    task_type: str
    metrics: dict[str, float]


class TuneRequest(BaseModel):
    """Same contraction as TrainRequest — dataset_id/target_column/task_type are
    inherited from the parent experiment."""

    model_config = _ML

    model_type: str
    n_trials: int = 20
    feature_columns: list[str] | None = None
    time_column: str | None = None
    notes: str = ""


class TrialOut(BaseModel):
    number: int
    run_id: str
    mlflow_run_id: str
    params: dict[str, Any]
    value: float | None
    std: float | None
    status: str


class TuneOut(BaseModel):
    model_config = _ML

    n_trials: int
    task_type: str
    objective_metric: str
    direction: str
    best_run_id: str | None
    best_metrics: dict[str, float]
    trials: list[TrialOut]


class RunDetailOut(BaseModel):
    model_config = _ML

    id: str
    mlflow_run_id: str
    # The investigation this run belongs to (D33). Exposed because a run is no
    # longer addressable on its own in the UI: findings and API callers key on a
    # run id, and without this there is no way to build the link back to the
    # leaderboard the run lives on.
    experiment_id: str
    dataset_id: str | None
    dataset_version: str | None
    model_type: str
    task_type: str
    notes: str
    notes_status: str
    created_at: dt.datetime
    status: str | None
    params: dict[str, str]
    metrics: dict[str, float]
    mlflow_available: bool


class RunPatchRequest(BaseModel):
    """Both fields optional: an edit, an approval, or both in one call.

    `None` means "leave it alone" — distinct from `notes=""`, which clears the
    note. A bare `{}` is accepted and changes nothing.
    """

    notes: str | None = None
    notes_status: Literal["draft", "approved", "rejected"] | None = None


class FindingOut(BaseModel):
    id: str
    source_type: str
    source_id: str
    text: str
    original_text: str
    status: str
    created_at: dt.datetime


class FindingPatchRequest(BaseModel):
    text: str | None = None
    status: str | None = None


class FindingCreatedOut(BaseModel):
    """The 201 body of both generation endpoints (§4.4)."""

    finding_id: str
    source_type: str
    source_id: str
    status: str
    text: str


class ExperimentCreateRequest(BaseModel):
    model_config = _ML

    name: str
    target_column: str
    objective: str = ""
    dataset_id: str | None = None
    # No dataset_version here on purpose: it is the content hash of the dataset
    # named above, so the route reads it off that row rather than letting a
    # caller assert a provenance that disagrees with what was actually scored.
    task_type: Literal["regression", "classification"] = "regression"


class ExperimentOut(BaseModel):
    model_config = _ML

    id: str
    name: str
    objective: str
    dataset_id: str | None
    # Resolved by the route, not stored. The list and leaderboard headers used to
    # render the raw uuid, which tells a reader nothing about which data the
    # investigation is over. None when the dataset was deleted (dataset_id is
    # ON DELETE SET NULL) or was never set.
    dataset_name: str | None
    dataset_version: str | None
    target_column: str
    task_type: str
    primary_metric: str
    metric_direction: str
    n_runs: int
    created_at: dt.datetime


class ExperimentPatchRequest(BaseModel):
    """`None` means "leave it alone", matching RunPatchRequest's convention."""

    name: str | None = None
    objective: str | None = None
    # Accepted only while the stored target is empty — a repair for the backfill's
    # unknowable case, not an edit. See update_experiment.
    target_column: str | None = None


class LeaderboardRowOut(BaseModel):
    model_config = _ML

    run: RunDetailOut
    rank: int | None
    value: float | None
    cv_value: float | None
    cv_std: float | None
    is_best: bool
    within_noise: bool


class LeaderboardOut(BaseModel):
    model_config = _ML

    primary_metric: str
    metric_direction: str
    # False when the tracking store is unreachable: rows fall back to
    # created_at order and every metric field is None (§7.4).
    ranked: bool
    mlflow_available: bool
    rows: list[LeaderboardRowOut]


class AgentChatRequest(BaseModel):
    """Stateless and single-shot (3.6): no chat id, no history. Extra fields are
    rejected so a client that thinks it is continuing a conversation finds out."""

    model_config = ConfigDict(extra="forbid")

    question: str = Field(min_length=1)

    @field_validator("question")
    @classmethod
    def _not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("question must not be blank")
        return value


class RetrievedOut(BaseModel):
    """One retrieved source. `run_id` is null for an eda hit — it is about a
    dataset, not a run — which is what the UI switches its deep link on."""

    source_type: str
    source_id: str
    run_id: str | None
    experiment_id: str | None
    dataset_id: str | None
    snippet: str
    score: float


class AgentStepOut(BaseModel):
    type: str
    model: str = ""
    tokens_in: int = 0
    tokens_out: int = 0
    latency_ms: int = 0
    tool_name: str | None = None
    tool_args: dict[str, Any] | None = None
    result_summary: str | None = None
    error: str | None = None


class AgentTraceOut(BaseModel):
    steps: list[AgentStepOut]
    tokens_in: int
    tokens_out: int
    cost_usd: float
    latency_ms: int


class AgentChatOut(BaseModel):
    """Deliberately has no `system_prompt` field. Same rule as the loop trace
    (issue #9): the assembled prompt can leak guardrail language, so it is not
    returned, not stored, and has no UI toggle."""

    answer: str
    retrieved: list[RetrievedOut]
    warnings: list[str]
    trace: AgentTraceOut
