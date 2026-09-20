import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, expect, test, vi } from "vitest";
import NewRunDialog from "./NewRunDialog";
import type { ExperimentRow } from "../types";
import * as api from "../api";
import { ApiError } from "../api";

const experiment: ExperimentRow = {
  id: "e1",
  name: "nowcast",
  objective: "beat persistence",
  dataset_id: "d1",
  dataset_name: "panel.csv",
  dataset_version: null,
  target_column: "revenue_next",
  task_type: "regression",
  primary_metric: "rmse",
  metric_direction: "minimize",
  n_runs: 3,
  created_at: "2026-08-22T00:00:00Z",
};

const models = [
  {
    model_type: "ridge",
    task_type: "regression",
    tunable: true,
    hyperparams: [{ name: "alpha", type: "float" as const, min: 0.001, max: 1000, log_scale: true }],
    column_hyperparams: [],
  },
  {
    model_type: "persistence",
    task_type: "regression",
    tunable: false,
    hyperparams: [],
    column_hyperparams: ["prior_column"],
  },
  {
    model_type: "logistic",
    task_type: "classification",
    tunable: true,
    hyperparams: [{ name: "C", type: "float" as const, min: 0.01, max: 100, log_scale: true }],
    column_hyperparams: [],
  },
];

const columns = [
  { name: "quarter", inferred_type: "datetime", null_count: 0 },
  { name: "revenue", inferred_type: "numeric", null_count: 0 },
  { name: "revenue_next", inferred_type: "numeric", null_count: 0 },
];

beforeEach(() => {
  vi.spyOn(api, "listModels").mockResolvedValue(models);
  vi.spyOn(api, "getDataset").mockResolvedValue({
    id: "d1",
    name: "panel.csv",
    n_rows: 224,
    n_cols: 3,
    columns,
  });
});

function renderDialog(onCreated = vi.fn()) {
  render(<NewRunDialog experiment={experiment} onCreated={onCreated} />);
  return onCreated;
}

async function open() {
  await userEvent.click(screen.getByRole("button", { name: "New run" }));
  return screen.findByRole("combobox", { name: "Model" });
}

test("renders closed until the trigger is clicked", () => {
  renderDialog();
  expect(screen.getByRole("button", { name: "New run" })).toBeInTheDocument();
  expect(screen.queryByRole("combobox", { name: "Model" })).not.toBeInTheDocument();
});

test("offers only models matching the experiment's task type", async () => {
  renderDialog();
  const select = await open();
  // `logistic` is a classifier; this investigation is a regression, and the
  // backend would 422 on it.
  expect([...select.querySelectorAll("option")].map((o) => o.textContent)).toEqual([
    "ridge",
    "persistence",
  ]);
});

test("renders one number input per tunable hyperparameter", async () => {
  renderDialog();
  await open();
  expect(await screen.findByRole("spinbutton", { name: "alpha" })).toBeInTheDocument();
});

test("a column-valued hyperparameter is a column picker, not a number box", async () => {
  renderDialog();
  const select = await open();
  await userEvent.selectOptions(select, "persistence");
  const prior = await screen.findByRole("combobox", { name: "prior_column" });
  expect([...prior.querySelectorAll("option")].map((o) => o.textContent)).toEqual([
    // The picker opens on a placeholder rather than on a column, so an unmade
    // choice is visibly unmade.
    "Select a column…",
    "quarter",
    "revenue",
  ]);
  expect(screen.queryByRole("spinbutton", { name: "alpha" })).not.toBeInTheDocument();
});

test("column pickers exclude the experiment's target column", async () => {
  renderDialog();
  await open();
  const time = await screen.findByRole("combobox", { name: "Time column" });
  const names = [...time.querySelectorAll("option")].map((o) => o.textContent);
  expect(names).not.toContain("revenue_next");
});

test("tuning is refused for a model with an empty search space", async () => {
  renderDialog();
  const select = await open();
  expect(screen.getByRole("radio", { name: "Tune" })).toBeEnabled();
  await userEvent.selectOptions(select, "persistence");
  // POST /experiments/{id}/tune 422s on persistence (D25) — do not let the
  // form send a request the backend is guaranteed to reject.
  expect(screen.getByRole("radio", { name: "Tune" })).toBeDisabled();
});

test("tune mode replaces the hyperparameter inputs with a trial count", async () => {
  renderDialog();
  await open();
  await userEvent.click(screen.getByRole("radio", { name: "Tune" }));
  expect(screen.getByRole("spinbutton", { name: "Trials" })).toHaveValue(20);
  expect(screen.queryByRole("spinbutton", { name: "alpha" })).not.toBeInTheDocument();
});

test("submitting trains with the assembled body and reports the new run", async () => {
  const trainRun = vi.spyOn(api, "trainRun").mockResolvedValue({
    run_id: "r9",
    mlflow_run_id: "m9",
    status: "FINISHED",
    task_type: "regression",
    metrics: { rmse: 1.5 },
  });
  const onCreated = renderDialog();
  await open();
  await userEvent.clear(await screen.findByRole("spinbutton", { name: "alpha" }));
  await userEvent.type(screen.getByRole("spinbutton", { name: "alpha" }), "2.5");
  await userEvent.selectOptions(screen.getByRole("combobox", { name: "Time column" }), "quarter");
  await userEvent.click(screen.getByRole("button", { name: "Launch" }));

  await waitFor(() => expect(trainRun).toHaveBeenCalled());
  expect(trainRun).toHaveBeenCalledWith("e1", {
    model_type: "ridge",
    hyperparams: { alpha: 2.5 },
    time_column: "quarter",
    notes: "",
  });
  await waitFor(() => expect(onCreated).toHaveBeenCalled());
});

test("submitting in tune mode runs a search", async () => {
  const tuneRun = vi.spyOn(api, "tuneRun").mockResolvedValue({
    n_trials: 5,
    task_type: "regression",
    objective_metric: "rmse",
    direction: "minimize",
    best_run_id: "r3",
    best_metrics: { rmse: 1.2 },
    trials: [],
  });
  const onCreated = renderDialog();
  await open();
  await userEvent.click(screen.getByRole("radio", { name: "Tune" }));
  await userEvent.clear(screen.getByRole("spinbutton", { name: "Trials" }));
  await userEvent.type(screen.getByRole("spinbutton", { name: "Trials" }), "5");
  await userEvent.click(screen.getByRole("button", { name: "Launch" }));

  await waitFor(() => expect(tuneRun).toHaveBeenCalled());
  expect(tuneRun).toHaveBeenCalledWith("e1", { model_type: "ridge", n_trials: 5, notes: "" });
  await waitFor(() => expect(onCreated).toHaveBeenCalled());
});

test("shows the backend's rejection verbatim", async () => {
  vi.spyOn(api, "trainRun").mockRejectedValue(
    new ApiError(422, "unknown time_column 'quarter'; known: ['revenue']"),
  );
  const onCreated = renderDialog();
  await open();
  await userEvent.click(screen.getByRole("button", { name: "Launch" }));
  // The backend's message names the offending value; a generic "Training
  // failed" would throw that away and leave the form unfixable.
  expect(
    await screen.findByText("unknown time_column 'quarter'; known: ['revenue']"),
  ).toBeInTheDocument();
  expect(onCreated).not.toHaveBeenCalled();
});

test("will not launch until a column hyperparameter has actually been chosen", async () => {
  // The picker used to display the first column while its state stayed empty,
  // and submit filled the gap with that same first column. A persistence
  // baseline fitted on an arbitrary prior still fits, still logs, and still
  // becomes the anchor every other run on the leaderboard is measured against.
  renderDialog();
  const select = await open();
  await userEvent.selectOptions(select, "persistence");
  await screen.findByRole("combobox", { name: "prior_column" });

  const launch = screen.getByRole("button", { name: "Launch" });
  expect(launch).toBeDisabled();
  expect(screen.getByText(/choose a value for prior_column/i)).toBeInTheDocument();

  await userEvent.selectOptions(
    screen.getByRole("combobox", { name: "prior_column" }),
    "revenue",
  );

  expect(launch).toBeEnabled();
});

test("sends the chosen prior column, never a positional guess", async () => {
  const trainRun = vi.spyOn(api, "trainRun").mockResolvedValue({ id: "r9" } as never);
  renderDialog();
  const select = await open();
  await userEvent.selectOptions(select, "persistence");
  await userEvent.selectOptions(
    await screen.findByRole("combobox", { name: "prior_column" }),
    "revenue",
  );
  await userEvent.click(screen.getByRole("button", { name: "Launch" }));

  await vi.waitFor(() =>
    expect(trainRun).toHaveBeenCalledWith(
      "e1",
      expect.objectContaining({ hyperparams: { prior_column: "revenue" } }),
    ),
  );
});
