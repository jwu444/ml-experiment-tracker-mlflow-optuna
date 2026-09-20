import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, expect, test, vi } from "vitest";
import NewExperimentDialog from "./NewExperimentDialog";
import * as api from "../api";
import { ApiError } from "../api";

const created = {
  id: "e9",
  name: "nowcast v2",
  objective: "beat persistence",
  dataset_id: "d1",
  dataset_name: "panel.csv",
  dataset_version: null,
  target_column: "revenue_next",
  task_type: "regression",
  primary_metric: "rmse",
  metric_direction: "minimize",
  n_runs: 0,
  created_at: "2026-08-24T00:00:00Z",
};

beforeEach(() => {
  vi.spyOn(api, "listDatasets").mockResolvedValue([
    { id: "d1", name: "panel.csv", n_rows: 224, n_cols: 3 },
    { id: "d2", name: "cpu.csv", n_rows: 1000, n_cols: 8 },
  ]);
  vi.spyOn(api, "getDataset").mockResolvedValue({
    id: "d1",
    name: "panel.csv",
    n_rows: 224,
    n_cols: 3,
    columns: [
      { name: "quarter", inferred_type: "datetime", null_count: 0 },
      { name: "revenue", inferred_type: "numeric", null_count: 0 },
      { name: "revenue_next", inferred_type: "numeric", null_count: 0 },
    ],
  });
});

async function open() {
  await userEvent.click(screen.getByRole("button", { name: "New experiment" }));
  return screen.findByRole("combobox", { name: "Dataset" });
}

test("renders closed until the trigger is clicked", () => {
  render(<NewExperimentDialog onCreated={vi.fn()} />);
  expect(screen.queryByRole("combobox", { name: "Dataset" })).not.toBeInTheDocument();
});

test("the target column is picked from the chosen dataset's real columns", async () => {
  render(<NewExperimentDialog onCreated={vi.fn()} />);
  await open();
  const target = await screen.findByRole("combobox", { name: "Target column" });
  expect([...target.querySelectorAll("option")].map((o) => o.textContent)).toEqual([
    "quarter",
    "revenue",
    "revenue_next",
  ]);
});

test("cannot submit without a name", async () => {
  render(<NewExperimentDialog onCreated={vi.fn()} />);
  await open();
  expect(screen.getByRole("button", { name: "Create" })).toBeDisabled();
  await userEvent.type(screen.getByRole("textbox", { name: "Name" }), "nowcast v2");
  expect(screen.getByRole("button", { name: "Create" })).toBeEnabled();
});

test("creating sends the assembled body and hands back the new experiment", async () => {
  const createExperiment = vi.spyOn(api, "createExperiment").mockResolvedValue(created);
  const onCreated = vi.fn();
  render(<NewExperimentDialog onCreated={onCreated} />);
  await open();
  await userEvent.type(screen.getByRole("textbox", { name: "Name" }), "nowcast v2");
  await userEvent.type(screen.getByRole("textbox", { name: "Objective" }), "beat persistence");
  await userEvent.selectOptions(
    await screen.findByRole("combobox", { name: "Target column" }),
    "revenue_next",
  );

  await userEvent.click(screen.getByRole("button", { name: "Create" }));

  await waitFor(() => expect(createExperiment).toHaveBeenCalled());
  expect(createExperiment).toHaveBeenCalledWith({
    name: "nowcast v2",
    objective: "beat persistence",
    dataset_id: "d1",
    target_column: "revenue_next",
    task_type: "regression",
  });
  await waitFor(() => expect(onCreated).toHaveBeenCalledWith(created));
});

test("a duplicate name is reported, not swallowed", async () => {
  vi.spyOn(api, "createExperiment").mockRejectedValue(
    new ApiError(409, "an experiment named 'nowcast v2' already exists"),
  );
  const onCreated = vi.fn();
  render(<NewExperimentDialog onCreated={onCreated} />);
  await open();
  await userEvent.type(screen.getByRole("textbox", { name: "Name" }), "nowcast v2");
  await userEvent.click(screen.getByRole("button", { name: "Create" }));

  // Names are unique because they are the join to MLflow until the first run
  // is logged; a silently dropped 409 would look like a created experiment.
  expect(
    await screen.findByText("an experiment named 'nowcast v2' already exists"),
  ).toBeInTheDocument();
  expect(onCreated).not.toHaveBeenCalled();
});
