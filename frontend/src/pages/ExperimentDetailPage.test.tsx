import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { beforeEach, expect, test, vi } from "vitest";
import ExperimentDetailPage from "./ExperimentDetailPage";
import { ThemeProvider } from "../theme";
import * as api from "../api";

function renderAt(id: string) {
  return render(
    <ThemeProvider>
      <MemoryRouter initialEntries={[`/experiments/${id}`]}>
        <Routes>
          <Route path="/experiments/:experimentId" element={<ExperimentDetailPage />} />
        </Routes>
      </MemoryRouter>
    </ThemeProvider>,
  );
}

const run = (id: string, modelType = "ridge") => ({
  id, mlflow_run_id: `m-${id}`, experiment_id: "e1", dataset_id: "d1", dataset_version: null,
  model_type: modelType, task_type: "regression", notes: "", notes_status: "draft",
  created_at: "2026-08-22T00:00:00Z", status: "FINISHED", params: {},
  metrics: {}, mlflow_available: true,
});

beforeEach(() => {
  // The nav rail loads both lists of its own. Stubbing them at the api layer
  // keeps those requests out of the assertions below.
  vi.spyOn(api, "listDatasets").mockResolvedValue([]);
  vi.spyOn(api, "listExperiments").mockResolvedValue([]);
  vi.spyOn(api, "getExperiment").mockResolvedValue({
    id: "e1", name: "nowcast", objective: "beat persistence", dataset_id: "d1",
    dataset_name: "panel.csv",
    dataset_version: null, target_column: "revenue", task_type: "regression",
    primary_metric: "rmse", metric_direction: "minimize", n_runs: 2,
    created_at: "2026-08-22T00:00:00Z",
  });
});

test("shows the objective and marks the best run", async () => {
  vi.spyOn(api, "getLeaderboard").mockResolvedValue({
    primary_metric: "rmse", metric_direction: "minimize", ranked: true,
    mlflow_available: true,
    rows: [
      { run: run("a"), rank: 1, value: 3, cv_value: 3.1, cv_std: 0.1,
        is_best: true, within_noise: false },
      { run: run("b"), rank: 2, value: 9, cv_value: 9.2, cv_std: 0.2,
        is_best: false, within_noise: false },
    ],
  });
  renderAt("e1");
  expect(await screen.findByText("beat persistence")).toBeInTheDocument();
  expect(await screen.findByText(/best/i)).toBeInTheDocument();
});

test("says a within-noise win is not a real win", async () => {
  vi.spyOn(api, "getLeaderboard").mockResolvedValue({
    primary_metric: "rmse", metric_direction: "minimize", ranked: true,
    mlflow_available: true,
    rows: [
      { run: run("a"), rank: 1, value: 10, cv_value: 10.5, cv_std: 2,
        is_best: true, within_noise: true },
      { run: run("b"), rank: 2, value: 11, cv_value: 11.2, cv_std: 1.8,
        is_best: false, within_noise: false },
    ],
  });
  renderAt("e1");
  expect(await screen.findByText(/within noise/i)).toBeInTheDocument();
});

test("an unranked run is still listed", async () => {
  vi.spyOn(api, "getLeaderboard").mockResolvedValue({
    primary_metric: "rmse", metric_direction: "minimize", ranked: true,
    mlflow_available: true,
    rows: [
      { run: run("a"), rank: 1, value: 3, cv_value: null, cv_std: null,
        is_best: true, within_noise: false },
      { run: run("nometric"), rank: null, value: null, cv_value: null,
        cv_std: null, is_best: false, within_noise: false },
    ],
  });
  renderAt("e1");
  expect(await screen.findByText("nometric")).toBeInTheDocument();
});

test("warns instead of ranking when the tracking store is down", async () => {
  vi.spyOn(api, "getLeaderboard").mockResolvedValue({
    primary_metric: "rmse", metric_direction: "minimize", ranked: false,
    mlflow_available: false,
    rows: [{ run: run("a"), rank: null, value: null, cv_value: null,
             cv_std: null, is_best: false, within_noise: false }],
  });
  renderAt("e1");
  expect(await screen.findByText(/tracking store/i)).toBeInTheDocument();
});

function twoRuns() {
  return vi.spyOn(api, "getLeaderboard").mockResolvedValue({
    primary_metric: "rmse", metric_direction: "minimize", ranked: true,
    mlflow_available: true,
    rows: [
      { run: run("a"), rank: 1, value: 3, cv_value: 3.1, cv_std: 0.1,
        is_best: true, within_noise: false },
      { run: run("b"), rank: 2, value: 9, cv_value: 9.2, cv_std: 0.2,
        is_best: false, within_noise: false },
    ],
  });
}

test("writing a note does not approve it", async () => {
  // D20: the seeding script writes notes through this same route, so an
  // implicit approval here would pre-bless every draft it produces.
  twoRuns();
  const update = vi.spyOn(api, "updateRun").mockResolvedValue(run("a"));
  const user = userEvent.setup();
  renderAt("e1");

  await user.click(await screen.findByLabelText("Review notes for a"));
  await user.type(await screen.findByLabelText("Notes"), "looks fine");
  await user.click(screen.getByRole("button", { name: /^save/i }));

  expect(update).toHaveBeenCalledWith("a", { notes: "looks fine" });
  expect(update.mock.calls[0][1]).not.toHaveProperty("notes_status");
});

test("approving sends the status alongside the text", async () => {
  twoRuns();
  const update = vi.spyOn(api, "updateRun").mockResolvedValue(run("a"));
  const user = userEvent.setup();
  renderAt("e1");

  await user.click(await screen.findByLabelText("Review notes for a"));
  await user.type(await screen.findByLabelText("Notes"), "verified");
  await user.click(screen.getByRole("button", { name: /^approve/i }));

  expect(update).toHaveBeenCalledWith("a", { notes: "verified", notes_status: "approved" });
});

test("the diagnostics action is per run, not per experiment", async () => {
  twoRuns();
  const diag = vi.spyOn(api, "runDiagnostics").mockResolvedValue({ finding_id: "f1" } as never);
  const findings = vi.spyOn(api, "listFindings").mockResolvedValue([
    {
      id: "f1",
      source_type: "diagnostic",
      source_id: "b",
      text: "residuals fan out",
      original_text: "residuals fan out",
      status: "draft",
      created_at: "2026-08-12T00:00:00Z",
    } as never,
  ]);
  const user = userEvent.setup();
  renderAt("e1");

  await user.click(await screen.findByLabelText("Run diagnostics for b"));
  expect(diag).toHaveBeenCalledWith("b");

  // The write-up opens in place, under the run it is about — it used to land in a
  // separate /review queue, so generating it and reading it were two screens.
  const panel = await screen.findByRole("region", { name: /diagnostics — run b/i });
  expect(within(panel).getByText("residuals fan out")).toBeInTheDocument();
  // Narrowed server-side to this run, not fetched broadly and filtered here.
  expect(findings).toHaveBeenCalledWith({ source_type: "diagnostic", source_id: "b" });
});

test("the compare table marks the better value on each metric", async () => {
  vi.spyOn(api, "getLeaderboard").mockResolvedValue({
    primary_metric: "rmse", metric_direction: "minimize", ranked: true,
    mlflow_available: true,
    rows: [
      { run: { ...run("a"), metrics: { rmse: 3, r2: 0.4 } }, rank: 1, value: 3,
        cv_value: 3.1, cv_std: 0.1, is_best: true, within_noise: false },
      { run: { ...run("b"), metrics: { rmse: 9, r2: 0.8 } }, rank: 2, value: 9,
        cv_value: 9.2, cv_std: 0.2, is_best: false, within_noise: false },
    ],
  });
  const user = userEvent.setup();
  renderAt("e1");

  await user.click(await screen.findByLabelText("Select a for comparison"));
  await user.click(await screen.findByLabelText("Select b for comparison"));

  const compare = await screen.findByLabelText("Compare selected runs");
  // rmse minimizes, so the winner is the smaller number — a table that just
  // took the max would look identical on a maximizing metric.
  expect(within(compare).getByText("3").closest("td")).toHaveAttribute("data-winner", "true");
  expect(within(compare).getByText("9").closest("td")).not.toHaveAttribute("data-winner");
  // r2 maximizes, but the experiment's direction is "minimize". Marking a
  // winner on a secondary metric would apply that direction to it and badge
  // 0.4 — the WORSE R² — so no secondary cell may be marked at all.
  expect(within(compare).getByText("0.4").closest("td")).not.toHaveAttribute("data-winner");
  expect(within(compare).getByText("0.8").closest("td")).not.toHaveAttribute("data-winner");
});

/** Three models, one of them the persistence baseline — the model the old
 *  hardcoded filter list did not know about (#51). */
function threeModels() {
  return vi.spyOn(api, "getLeaderboard").mockResolvedValue({
    primary_metric: "rmse", metric_direction: "minimize", ranked: true,
    mlflow_available: true,
    rows: [
      { run: run("a", "ridge"), rank: 1, value: 3, cv_value: 3.1, cv_std: 0.1,
        is_best: true, within_noise: false },
      { run: run("b", "random_forest"), rank: 2, value: 9, cv_value: 9.2, cv_std: 0.2,
        is_best: false, within_noise: false },
      { run: run("c", "persistence"), rank: 3, value: 14, cv_value: null, cv_std: null,
        is_best: false, within_noise: false },
    ],
  });
}

test("the model filter offers every model on the leaderboard", async () => {
  // The regression in #51: the options came from a hand-maintained list, so a
  // model added to MODEL_REGISTRY was unfilterable. Deriving them from the
  // loaded runs is what makes that impossible to repeat.
  threeModels();
  renderAt("e1");

  const select = await screen.findByLabelText("Model type");
  const options = within(select).getAllByRole("option").map((o) => o.textContent);
  expect(options).toEqual(["All models", "persistence", "random_forest", "ridge"]);
});

test("choosing a model hides the other models' runs", async () => {
  threeModels();
  const user = userEvent.setup();
  renderAt("e1");

  await user.selectOptions(await screen.findByLabelText("Model type"), "persistence");
  const board = screen.getByRole("table", { name: "Leaderboard" });
  expect(within(board).getByText("persistence")).toBeInTheDocument();
  expect(within(board).queryByText("ridge")).not.toBeInTheDocument();
});

test("filtering does not renumber the ranks", async () => {
  // D38 ranks within the whole investigation. Renumbering the filtered view
  // would report the baseline as rank 1 — a claim the backend never made.
  threeModels();
  const user = userEvent.setup();
  renderAt("e1");

  await user.selectOptions(await screen.findByLabelText("Model type"), "persistence");
  const board = screen.getByRole("table", { name: "Leaderboard" });
  const row = within(board).getByText("persistence").closest("tr") as HTMLElement;
  expect(within(row).getByText("3")).toBeInTheDocument();
});

test("changing the filter drops the comparison selection", async () => {
  // A selected row that the filter then hides has no reachable checkbox, so
  // it would feed an invisible run into the compare table forever.
  threeModels();
  const user = userEvent.setup();
  renderAt("e1");

  await user.click(await screen.findByLabelText("Select a for comparison"));
  await user.click(screen.getByLabelText("Select b for comparison"));
  expect(screen.getByRole("table", { name: "Compare selected runs" })).toBeInTheDocument();

  await user.selectOptions(screen.getByLabelText("Model type"), "ridge");
  expect(screen.queryByRole("table", { name: "Compare selected runs" })).not.toBeInTheDocument();
});

test("a launched run is never hidden behind the filter that was set before it", async () => {
  // The filter narrows to models already on the board, so a run of any OTHER
  // model lands outside it. Left in place, the launch reported success, the
  // header count went up, and the table did not move — the one row the user
  // asked for was the one row they could not see.
  threeModels();
  vi.spyOn(api, "listModels").mockResolvedValue([
    {
      model_type: "ridge",
      task_type: "regression",
      tunable: true,
      hyperparams: [{ name: "alpha", type: "float" as const, min: 0.01, max: 10, log_scale: true }],
      column_hyperparams: [],
    },
  ] as never);
  vi.spyOn(api, "getDataset").mockResolvedValue({
    id: "d1",
    name: "panel.csv",
    n_rows: 224,
    n_cols: 2,
    columns: [{ name: "quarter", inferred_type: "datetime", null_count: 0 }],
  } as never);
  vi.spyOn(api, "trainRun").mockResolvedValue({ id: "r9" } as never);
  const user = userEvent.setup();
  renderAt("e1");

  await user.selectOptions(await screen.findByLabelText("Model type"), "persistence");
  const board = screen.getByRole("table", { name: "Leaderboard" });
  expect(within(board).queryByText("ridge")).not.toBeInTheDocument();

  await user.click(screen.getByRole("button", { name: "New run" }));
  await screen.findByRole("combobox", { name: "Model" });
  await user.click(screen.getByRole("button", { name: "Launch" }));

  await vi.waitFor(() =>
    expect(screen.getByLabelText("Model type")).toHaveValue(""),
  );
  expect(
    within(screen.getByRole("table", { name: "Leaderboard" })).getByText("ridge"),
  ).toBeInTheDocument();
});
