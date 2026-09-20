import { render, screen, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import ExperimentsPage from "./ExperimentsPage";
import * as api from "../api";
import { ThemeProvider } from "../theme";

const rows = [
  {
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
  },
  {
    id: "e2",
    name: "gpu-price",
    objective: "predict launch price",
    dataset_id: "d2",
    dataset_name: null,
    dataset_version: null,
    target_column: "price",
    task_type: "regression",
    primary_metric: "rmse",
    metric_direction: "minimize",
    n_runs: 0,
    created_at: "2026-08-11T00:00:00Z",
  },
];

function renderPage() {
  render(
    <ThemeProvider>
      <MemoryRouter>
        <ExperimentsPage />
      </MemoryRouter>
    </ThemeProvider>,
  );
}

beforeEach(() => {
  vi.restoreAllMocks();
  // The nav rail loads both lists of its own, and it lists the same
  // investigations this page tabulates — so every assertion below is scoped to
  // the table rather than to the whole document.
  vi.spyOn(api, "listDatasets").mockResolvedValue([]);
  vi.spyOn(api, "listExperiments").mockResolvedValue(rows);
});

describe("ExperimentsPage", () => {
  it("lists every investigation with its objective, dataset and run count", async () => {
    renderPage();
    const table = within(await screen.findByRole("table"));
    expect(table.getByText("nowcast")).toBeInTheDocument();
    expect(table.getByText("beat persistence")).toBeInTheDocument();
    // The dataset column shows the name, never the raw uuid...
    expect(table.getByText("revenue_nowcast.csv")).toBeInTheDocument();
    expect(table.queryByText("d1")).not.toBeInTheDocument();
    // ...but e2's dataset row is gone (dataset_name null), so the id is all
    // that is left to identify it — better than an empty cell.
    expect(table.getByText("d2")).toBeInTheDocument();
    expect(table.getByText("3")).toBeInTheDocument();
    expect(table.getByText("gpu-price")).toBeInTheDocument();
  });

  it("links each row to its investigation detail page", async () => {
    renderPage();
    const table = within(await screen.findByRole("table"));
    const link = table.getByRole("link", { name: "nowcast" });
    expect(link).toHaveAttribute("href", "/experiments/e1");
  });

  it("shows an empty state when there are no investigations", async () => {
    vi.spyOn(api, "listExperiments").mockResolvedValue([]);
    renderPage();
    expect(await screen.findByText(/no experiments yet/i)).toBeInTheDocument();
  });

  it("shows a banner when the list request fails", async () => {
    vi.spyOn(api, "listExperiments").mockRejectedValue(new api.ApiError(503, "MLflow is down"));
    renderPage();
    expect(await screen.findByRole("alert")).toHaveTextContent("MLflow is down");
  });
});
