export interface DatasetOut {
  id: string;
  name: string;
  n_rows: number;
  n_cols: number;
}

export interface DatasetColumn {
  name: string;
  inferred_type: string;
  null_count: number;
}

/** `GET /datasets/{id}` only. The list route stays on `DatasetOut` — it is
 *  rendered as a nav sidebar and has nothing to do with the columns. */
export interface DatasetDetail extends DatasetOut {
  columns: DatasetColumn[];
}

/** One tunable hyperparameter, flattened out of a `ModelSpec.search_space`
 *  entry by `GET /models`. */
export interface HyperparamSpec {
  name: string;
  type: "int" | "float";
  min: number;
  max: number;
  log_scale: boolean;
}

/** One `MODEL_REGISTRY` entry. Served by `GET /models` rather than restated
 *  in the frontend: a hand-maintained copy of this list is what made the
 *  leaderboard filter silently hide `persistence` runs (#51). */
export interface ModelSpec {
  model_type: string;
  task_type: string;
  /** False when the search space is empty — `POST /experiments/{id}/tune`
   *  422s on such a model (D25), so the form must not offer Tune for it. */
  tunable: boolean;
  hyperparams: HyperparamSpec[];
  /** Hyperparameters whose value is one of the dataset's column names. They
   *  are required to fit but have nothing to search over, so they appear here
   *  and not in `hyperparams` — the form renders a column picker for each. */
  column_hyperparams: string[];
}

export interface ChatDatasetOut {
  id: string;
  name: string;
}

export interface ChatOut {
  id: string;
  datasets: ChatDatasetOut[];
}

export interface AnalystPassOut {
  model: string;
  tokens_in: number;
  tokens_out: number;
  latency_ms: number;
  cost_usd: number;
  interpretation: string;
}

export interface JudgePassOut {
  model: string;
  tokens_in: number;
  tokens_out: number;
  latency_ms: number;
  cost_usd: number;
  score: number | null;
  feedback: string;
  gaps: string[];
}

export interface PassTraceOut {
  pass_no: number;
  analyst: AnalystPassOut;
  charts: string[];
  stats: Record<string, unknown>[];
  errors: string[];
  judge: JudgePassOut;
  revision_instruction: string;
}

export interface MessageTraceOut {
  passes: PassTraceOut[];
}

export interface ChatMessageOut {
  id: string;
  role: string;
  content: string;
  charts: string[];
  stats: Record<string, unknown>[];
  errors: string[];
  // Per-pass loop trace (issue #9 review); absent/null for user + pre-trace rows.
  trace?: MessageTraceOut | null;
}

export interface ChatHistoryOut {
  datasets: ChatDatasetOut[];
  messages: ChatMessageOut[];
}

/** D20's three review states. `draft` is what the machine writes; only a human
 *  moves a note off it, and Phase 3 embeds the approved ones only. */
export type NotesStatus = "draft" | "approved" | "rejected";

/** One trained model run (formerly the whole of `ExperimentRow`, before the
 *  parent `Experiment` investigation was introduced above it). */
export interface RunRow {
  id: string;
  mlflow_run_id: string;
  /** The investigation this run belongs to. A run has no page of its own —
   *  this is how a diagnostic finding is linked back to a leaderboard. */
  experiment_id: string;
  dataset_id: string | null;
  dataset_version: string | null;
  model_type: string;
  task_type: string;
  notes: string;
  notes_status: string;
  created_at: string;
  // Below this line the values come from MLflow, not from our own tables. When
  // the tracking store is unreachable the backend still answers, with these
  // empty and mlflow_available false — a read must not 500 on a down store.
  status: string | null;
  params: Record<string, string>;
  metrics: Record<string, number>;
  mlflow_available: boolean;
}

/** An investigation: the parent that owns many `RunRow`s and carries the
 *  fields that used to live on a run (dataset, task_type) plus the ones that
 *  only make sense once per investigation (name, objective, primary_metric). */
export interface ExperimentRow {
  id: string;
  name: string;
  objective: string;
  dataset_id: string | null;
  /** Resolved by the backend so the UI never has to render a raw uuid at a
   *  reader. Null if the dataset was deleted or was never set. */
  dataset_name: string | null;
  dataset_version: string | null;
  target_column: string;
  task_type: string;
  primary_metric: string;
  metric_direction: string;
  n_runs: number;
  created_at: string;
}

export interface LeaderboardRow {
  run: RunRow;
  /** null when this run has no value for the ranking metric — it sorts last
   *  and is shown unranked rather than dropped. */
  rank: number | null;
  value: number | null;
  cv_value: number | null;
  cv_std: number | null;
  is_best: boolean;
  /** The leader's margin over second place is smaller than its own cv_std. */
  within_noise: boolean;
}

export interface Leaderboard {
  primary_metric: string;
  metric_direction: string;
  ranked: boolean;
  mlflow_available: boolean;
  rows: LeaderboardRow[];
}

/** One retrieved source. `run_id` is null for an `eda` hit — it is about a
 *  dataset, not a run — which is what the citation's deep link switches on. */
export interface Retrieved {
  source_type: "note" | "eda" | "diagnostic";
  source_id: string;
  run_id: string | null;
  experiment_id: string | null;
  dataset_id: string | null;
  snippet: string;
  score: number;
}

export interface AgentStep {
  type: "llm" | "tool";
  model: string;
  tokens_in: number;
  tokens_out: number;
  latency_ms: number;
  tool_name: string | null;
  tool_args: Record<string, unknown> | null;
  result_summary: string | null;
  error: string | null;
}

export interface AgentTrace {
  steps: AgentStep[];
  tokens_in: number;
  tokens_out: number;
  cost_usd: number;
  latency_ms: number;
}

export interface AgentAnswer {
  answer: string;
  retrieved: Retrieved[];
  warnings: string[];
  trace: AgentTrace;
}
