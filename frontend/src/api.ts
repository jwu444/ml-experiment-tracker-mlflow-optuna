import type {
  AgentAnswer,
  ChatHistoryOut,
  ChatMessageOut,
  ChatOut,
  DatasetDetail,
  DatasetOut,
  ExperimentRow,
  Leaderboard,
  ModelSpec,
  NotesStatus,
  RunRow,
} from "./types";

const API_BASE = import.meta.env.VITE_API_BASE ?? "/api";

export class ApiError extends Error {
  status: number;

  constructor(status: number, message: string) {
    super(message);
    this.name = "ApiError";
    this.status = status;
  }
}

async function failFrom(res: Response): Promise<never> {
  let detail = res.statusText || `HTTP ${res.status}`;
  try {
    const body = (await res.json()) as { detail?: unknown };
    if (typeof body.detail === "string") detail = body.detail;
  } catch {
    // Non-JSON error body — keep the status-based message.
  }
  throw new ApiError(res.status, detail);
}

export async function uploadDataset(file: File): Promise<DatasetOut> {
  const form = new FormData();
  form.append("file", file);
  const res = await fetch(`${API_BASE}/datasets`, { method: "POST", body: form });
  if (!res.ok) return failFrom(res);
  return res.json() as Promise<DatasetOut>;
}

/** Returns the dataset *with* its columns — the detail route carries them so a
 *  form can offer real column names instead of a free-text box. */
export async function getDataset(id: string): Promise<DatasetDetail> {
  const res = await fetch(`${API_BASE}/datasets/${id}`);
  if (!res.ok) return failFrom(res);
  return res.json() as Promise<DatasetDetail>;
}

export async function listDatasets(): Promise<DatasetOut[]> {
  const res = await fetch(`${API_BASE}/datasets`);
  if (!res.ok) return failFrom(res);
  return res.json() as Promise<DatasetOut[]>;
}

export async function createChat(datasetIds: string[]): Promise<ChatOut> {
  const res = await fetch(`${API_BASE}/chats`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ dataset_ids: datasetIds }),
  });
  if (!res.ok) return failFrom(res);
  return res.json() as Promise<ChatOut>;
}

export async function getChatHistory(chatId: string): Promise<ChatHistoryOut> {
  const res = await fetch(`${API_BASE}/chats/${chatId}`);
  if (!res.ok) return failFrom(res);
  return res.json() as Promise<ChatHistoryOut>;
}

export async function postChat(chatId: string, question: string): Promise<ChatMessageOut> {
  const res = await fetch(`${API_BASE}/chats/${chatId}/messages`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ question }),
  });
  if (!res.ok) return failFrom(res);
  return res.json() as Promise<ChatMessageOut>;
}

/** Lists investigations, not runs — `model_type` and `notes_status` no longer
 *  apply at this level (D34); filter runs themselves via `listRuns`. */
export async function listExperiments(
  params: { datasetId?: string; taskType?: string } = {},
): Promise<ExperimentRow[]> {
  const q = new URLSearchParams();
  if (params.datasetId) q.set("dataset_id", params.datasetId);
  if (params.taskType) q.set("task_type", params.taskType);
  const qs = q.toString();
  const res = await fetch(`${API_BASE}/experiments${qs ? `?${qs}` : ""}`);
  if (!res.ok) return failFrom(res);
  return res.json() as Promise<ExperimentRow[]>;
}

export async function createExperiment(body: {
  name: string;
  target_column: string;
  objective?: string;
  dataset_id?: string | null;
  // No dataset_version: the backend pins it from the dataset's content hash,
  // so sending one here would be ignored rather than honoured.
  task_type?: string;
}): Promise<ExperimentRow> {
  const res = await fetch(`${API_BASE}/experiments`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!res.ok) return failFrom(res);
  return res.json() as Promise<ExperimentRow>;
}

export async function getExperiment(id: string): Promise<ExperimentRow> {
  const res = await fetch(`${API_BASE}/experiments/${id}`);
  if (!res.ok) return failFrom(res);
  return res.json() as Promise<ExperimentRow>;
}

/** `name`/`objective` are the only editable fields on an investigation — notes
 *  now live on the run (`updateRun`), not the investigation (D34). */
export async function updateExperiment(
  id: string,
  patch: { name?: string; objective?: string },
): Promise<ExperimentRow> {
  const res = await fetch(`${API_BASE}/experiments/${id}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(patch),
  });
  if (!res.ok) return failFrom(res);
  return res.json() as Promise<ExperimentRow>;
}

/** The training registry, straight from `MODEL_REGISTRY` (#52). */
export async function listModels(): Promise<ModelSpec[]> {
  const res = await fetch(`${API_BASE}/models`);
  if (!res.ok) return failFrom(res);
  return res.json() as Promise<ModelSpec[]>;
}

export interface RunResult {
  run_id: string;
  mlflow_run_id: string;
  status: string;
  task_type: string;
  metrics: Record<string, number>;
}

export interface TrialResult {
  number: number;
  run_id: string;
  mlflow_run_id: string;
  params: Record<string, unknown>;
  value: number | null;
  std: number | null;
  status: string;
}

export interface TuneResult {
  n_trials: number;
  task_type: string;
  objective_metric: string;
  direction: string;
  best_run_id: string | null;
  best_metrics: Record<string, number>;
  trials: TrialResult[];
}

/** Launch one training run inside an investigation. `dataset_id`,
 *  `target_column` and `task_type` are the parent's and are deliberately not
 *  accepted here — a run cannot disagree with the experiment it belongs to
 *  (D34). Runs synchronously inside the request, so this call is slow. */
export async function trainRun(
  experimentId: string,
  body: {
    model_type: string;
    hyperparams?: Record<string, number | string>;
    feature_columns?: string[] | null;
    time_column?: string | null;
    notes?: string;
  },
): Promise<RunResult> {
  const res = await fetch(`${API_BASE}/experiments/${experimentId}/train`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!res.ok) return failFrom(res);
  return res.json() as Promise<RunResult>;
}

/** Launch an Optuna search inside an investigation. Each trial is logged as
 *  its own run, so the leaderboard gains `n_trials` rows, not one. */
export async function tuneRun(
  experimentId: string,
  body: {
    model_type: string;
    n_trials?: number;
    feature_columns?: string[] | null;
    time_column?: string | null;
    notes?: string;
  },
): Promise<TuneResult> {
  const res = await fetch(`${API_BASE}/experiments/${experimentId}/tune`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!res.ok) return failFrom(res);
  return res.json() as Promise<TuneResult>;
}

/** The experiment-scoped leaderboard (D38): runs ranked within one
 *  investigation, never across investigations on unrelated scales. */
export async function getLeaderboard(experimentId: string): Promise<Leaderboard> {
  const res = await fetch(`${API_BASE}/experiments/${experimentId}/runs`);
  if (!res.ok) return failFrom(res);
  return res.json() as Promise<Leaderboard>;
}

export async function listRuns(
  params: {
    modelType?: string;
    taskType?: string;
    datasetId?: string;
    experimentId?: string;
    notesStatus?: string;
    status?: string;
  } = {},
): Promise<RunRow[]> {
  const q = new URLSearchParams();
  if (params.modelType) q.set("model_type", params.modelType);
  if (params.taskType) q.set("task_type", params.taskType);
  if (params.datasetId) q.set("dataset_id", params.datasetId);
  if (params.experimentId) q.set("experiment_id", params.experimentId);
  if (params.notesStatus) q.set("notes_status", params.notesStatus);
  if (params.status) q.set("status", params.status);
  const qs = q.toString();
  const res = await fetch(`${API_BASE}/runs${qs ? `?${qs}` : ""}`);
  if (!res.ok) return failFrom(res);
  return res.json() as Promise<RunRow[]>;
}

export async function getRun(id: string): Promise<RunRow> {
  const res = await fetch(`${API_BASE}/runs/${id}`);
  if (!res.ok) return failFrom(res);
  return res.json() as Promise<RunRow>;
}

/** Edit and/or approve a run's note. Omit a field to leave it untouched —
 *  saving text is deliberately NOT an approval (D20). */
export async function updateRun(
  id: string,
  patch: { notes?: string; notes_status?: NotesStatus },
): Promise<RunRow> {
  const res = await fetch(`${API_BASE}/runs/${id}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(patch),
  });
  if (!res.ok) return failFrom(res);
  return res.json() as Promise<RunRow>;
}

export type Finding = {
  id: string;
  source_type: "eda" | "diagnostic";
  source_id: string;
  text: string;
  original_text: string;
  status: "draft" | "approved" | "rejected";
  created_at: string;
};

export type FindingCreated = {
  finding_id: string;
  source_type: string;
  source_id: string;
  status: string;
  text: string;
};

/** `source_id` narrows to one dataset's or one run's findings. The inline panels always
 *  send it: fetching broadly and filtering in the component would drop everything past
 *  the route's `limit` and render as "no findings yet". */
export async function listFindings(
  params: { status?: string; source_type?: string; source_id?: string } = {},
): Promise<Finding[]> {
  const query = new URLSearchParams();
  if (params.status) query.set("status", params.status);
  if (params.source_type) query.set("source_type", params.source_type);
  if (params.source_id) query.set("source_id", params.source_id);
  const suffix = query.toString() ? `?${query}` : "";
  const res = await fetch(`${API_BASE}/findings${suffix}`);
  if (!res.ok) return failFrom(res);
  return res.json() as Promise<Finding[]>;
}

export async function updateFinding(
  id: string,
  body: { text?: string; status?: string },
): Promise<Finding> {
  const res = await fetch(`${API_BASE}/findings/${id}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!res.ok) return failFrom(res);
  return res.json() as Promise<Finding>;
}

export async function runEda(datasetId: string): Promise<FindingCreated> {
  const res = await fetch(`${API_BASE}/datasets/${datasetId}/eda`, { method: "POST" });
  if (!res.ok) return failFrom(res);
  return res.json() as Promise<FindingCreated>;
}

export async function runDiagnostics(runId: string): Promise<FindingCreated> {
  const res = await fetch(`${API_BASE}/runs/${runId}/diagnostics`, {
    method: "POST",
  });
  if (!res.ok) return failFrom(res);
  return res.json() as Promise<FindingCreated>;
}

/** Ask the retrieval agent one question. Stateless: no chat id, no history. */
export async function askAgent(question: string): Promise<AgentAnswer> {
  const res = await fetch(`${API_BASE}/agent/chat`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ question }),
  });
  if (!res.ok) return failFrom(res);
  return res.json() as Promise<AgentAnswer>;
}
