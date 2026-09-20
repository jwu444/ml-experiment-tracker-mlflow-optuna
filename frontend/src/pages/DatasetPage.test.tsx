import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, expect, test, vi } from "vitest";
import { MemoryRouter, Route, Routes } from "react-router-dom";

import DatasetPage from "./DatasetPage";
import * as api from "../api";
import { ThemeProvider } from "../theme";

const detail = {
  id: "d1",
  name: "revenue_nowcast.csv",
  n_rows: 224,
  n_cols: 2,
  columns: [
    { name: "month", inferred_type: "datetime", null_count: 0 },
    { name: "revenue", inferred_type: "numeric", null_count: 3 },
  ],
};

function finding(text = "revenue is seasonal"): api.Finding {
  return {
    id: "f1",
    source_type: "eda",
    source_id: "d1",
    text,
    original_text: text,
    status: "draft",
    created_at: "2026-08-12T00:00:00Z",
  };
}

function renderPage() {
  render(
    <ThemeProvider>
      <MemoryRouter initialEntries={["/datasets/d1"]}>
        <Routes>
          <Route path="/datasets/:datasetId" element={<DatasetPage />} />
          <Route path="/c/:chatId" element={<p>chat opened</p>} />
        </Routes>
      </MemoryRouter>
    </ThemeProvider>,
  );
}

beforeEach(() => {
  vi.restoreAllMocks();
  // The nav rail loads both lists of its own.
  vi.spyOn(api, "listDatasets").mockResolvedValue([]);
  vi.spyOn(api, "listExperiments").mockResolvedValue([]);
  vi.spyOn(api, "getDataset").mockResolvedValue(detail);
  vi.spyOn(api, "listFindings").mockResolvedValue([]);
});

test("shows the dataset's shape and every column", async () => {
  renderPage();

  expect(await screen.findByRole("heading", { name: "revenue_nowcast.csv" })).toBeInTheDocument();
  expect(screen.getByText(/224 rows × 2 columns/)).toBeInTheDocument();
  const columns = within(screen.getByRole("table"));
  expect(columns.getByText("month")).toBeInTheDocument();
  expect(columns.getByText("revenue")).toBeInTheDocument();
  expect(columns.getByText("datetime")).toBeInTheDocument();
});

test("EDA and its write-ups live on the same page", async () => {
  const list = vi.spyOn(api, "listFindings").mockResolvedValue([finding("revenue is seasonal")]);
  renderPage();

  // Running EDA and reading the result used to be two different sections.
  expect(await screen.findByRole("button", { name: "Run EDA" })).toBeInTheDocument();
  const panel = await screen.findByRole("region", { name: "EDA findings" });
  expect(within(panel).getByText("revenue is seasonal")).toBeInTheDocument();
  expect(list).toHaveBeenCalledWith({ source_type: "eda", source_id: "d1" });
});

test("a completed EDA pass refetches, so the new draft appears without a reload", async () => {
  const list = vi.spyOn(api, "listFindings").mockResolvedValue([]);
  const eda = vi.spyOn(api, "runEda").mockResolvedValue({ finding_id: "f1" } as never);
  const user = userEvent.setup();
  renderPage();

  await screen.findByText("No EDA write-ups yet — run one above.");
  list.mockResolvedValue([finding("fresh from the loop")]);
  await user.click(screen.getByRole("button", { name: "Run EDA" }));

  expect(eda).toHaveBeenCalledWith("d1");
  expect(await screen.findByText("fresh from the loop")).toBeInTheDocument();
});

test("starting a chat from here opens it on this dataset", async () => {
  const create = vi
    .spyOn(api, "createChat")
    .mockResolvedValue({ id: "c1", dataset_ids: ["d1"] } as never);
  const user = userEvent.setup();
  renderPage();

  await user.click(await screen.findByRole("button", { name: "Start chat" }));
  expect(create).toHaveBeenCalledWith(["d1"]);
  expect(await screen.findByText("chat opened")).toBeInTheDocument();
});

test("a failed EDA pass is reported rather than swallowed", async () => {
  vi.spyOn(api, "runEda").mockRejectedValue(new api.ApiError(502, "the loop gave up"));
  const user = userEvent.setup();
  renderPage();

  await user.click(await screen.findByRole("button", { name: "Run EDA" }));
  expect(await screen.findByRole("alert")).toHaveTextContent("the loop gave up");
});
