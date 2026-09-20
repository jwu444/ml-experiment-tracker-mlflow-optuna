import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, expect, test, vi } from "vitest";
import { MemoryRouter } from "react-router-dom";

import NavRail from "./NavRail";
import * as api from "../api";
import type { ExperimentRow } from "../types";

const datasets = [
  { id: "d1", name: "revenue_nowcast.csv", n_rows: 224, n_cols: 12 },
  { id: "d2", name: "video-card.csv", n_rows: 900, n_cols: 8 },
];

function experiment(over: Partial<ExperimentRow> = {}): ExperimentRow {
  return {
    id: "e1",
    name: "nowcast",
    objective: "beat persistence",
    dataset_id: "d1",
    dataset_name: "revenue_nowcast.csv",
    dataset_version: null,
    target_column: "revenue",
    task_type: "regression",
    primary_metric: "rmse",
    metric_direction: "minimize",
    n_runs: 3,
    created_at: "2026-08-10T00:00:00Z",
    ...over,
  };
}

function renderRail() {
  render(
    <MemoryRouter>
      <NavRail />
    </MemoryRouter>,
  );
}

beforeEach(() => {
  vi.restoreAllMocks();
  localStorage.clear();
  vi.spyOn(api, "listDatasets").mockResolvedValue(datasets);
  vi.spyOn(api, "listExperiments").mockResolvedValue([experiment()]);
});

test("files each entity under the category that owns it", async () => {
  renderRail();
  const rail = await screen.findByRole("navigation", { name: "Sections" });

  expect(within(rail).getByText("Data")).toBeInTheDocument();
  expect(within(rail).getByText("Machine learning")).toBeInTheDocument();
  expect(await within(rail).findByRole("link", { name: /revenue_nowcast\.csv/ })).toHaveAttribute(
    "href",
    "/datasets/d1",
  );
  expect(within(rail).getByRole("link", { name: /nowcast 3 runs/ })).toHaveAttribute(
    "href",
    "/experiments/e1",
  );
  expect(within(rail).getByRole("link", { name: "All experiments" })).toHaveAttribute(
    "href",
    "/experiments",
  );
});

test("clicking a dataset opens its page rather than starting a chat", async () => {
  const create = vi.spyOn(api, "createChat");
  renderRail();

  const link = await screen.findByRole("link", { name: /video-card\.csv/ });
  await userEvent.setup().click(link);
  // The dataset page carries Start chat and Run EDA, and is where an EDA draft
  // lands — a bare row click should not commit the reader to a chat.
  expect(create).not.toHaveBeenCalled();
});

test("datasets stay multi-selectable, because a chat spans N of them (#6)", async () => {
  const create = vi
    .spyOn(api, "createChat")
    .mockResolvedValue({ id: "c1", dataset_ids: ["d1", "d2"] } as never);
  const user = userEvent.setup();
  renderRail();

  await user.click(await screen.findByLabelText("Select revenue_nowcast.csv"));
  await user.click(screen.getByLabelText("Select video-card.csv"));
  await user.click(screen.getByRole("button", { name: /start chat with 2 datasets/i }));
  // Datasets are fixed at chat creation, so both ids go in one call.
  expect(create).toHaveBeenCalledWith(["d1", "d2"]);
});

test("collapsing a group hides only its own entities, and persists", async () => {
  const user = userEvent.setup();
  renderRail();

  await user.click(await screen.findByRole("button", { name: /datasets/i }));
  expect(screen.queryByRole("link", { name: /revenue_nowcast\.csv/ })).not.toBeInTheDocument();
  // The other category is untouched — the two collapse independently.
  expect(screen.getByRole("link", { name: /nowcast 3 runs/ })).toBeInTheDocument();
  expect(localStorage.getItem("wp-rail-collapsed")).toBe("data");
});

test("a failed experiments fetch does not blank the datasets list", async () => {
  vi.spyOn(api, "listExperiments").mockRejectedValue(new api.ApiError(503, "MLflow is down"));
  renderRail();

  // Each list is a separate destination; one being unavailable must not take
  // the other's navigation down with it.
  expect(await screen.findByRole("link", { name: /revenue_nowcast\.csv/ })).toBeInTheDocument();
});

test("reports a failed datasets fetch instead of showing an empty section", async () => {
  vi.spyOn(api, "listDatasets").mockRejectedValue(new api.ApiError(500, "database unavailable"));
  renderRail();

  expect(await screen.findByRole("alert")).toHaveTextContent("database unavailable");
});
