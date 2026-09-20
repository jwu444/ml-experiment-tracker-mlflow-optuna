import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { vi, beforeEach } from "vitest";
import { MemoryRouter } from "react-router-dom";
import UploadPage from "./UploadPage";
import * as api from "../api";
import { ThemeProvider } from "../theme";

const navigateMock = vi.fn();
vi.mock("react-router-dom", async (importOriginal) => {
  const actual = await importOriginal<typeof import("react-router-dom")>();
  return { ...actual, useNavigate: () => navigateMock };
});

beforeEach(() => {
  vi.restoreAllMocks();
  navigateMock.mockReset();
  vi.spyOn(api, "listDatasets").mockResolvedValue([]);
});

function renderPage() {
  render(
    <ThemeProvider>
      <MemoryRouter>
        <UploadPage />
      </MemoryRouter>
    </ThemeProvider>,
  );
}

test("shows the upload hero heading", () => {
  renderPage();
  expect(screen.getByRole("heading", { name: /CSV Analysis Assistant/i })).toBeInTheDocument();
});

test("uploads a single chosen file and navigates to its chat", async () => {
  vi.spyOn(api, "uploadDataset").mockResolvedValue({
    id: "abc", name: "s.csv", n_rows: 3, n_cols: 2,
  });
  vi.spyOn(api, "createChat").mockResolvedValue({
    id: "chat1", datasets: [{ id: "abc", name: "s.csv" }],
  });
  renderPage();
  const file = new File(["a,b\n1,2\n"], "s.csv", { type: "text/csv" });

  await userEvent.upload(screen.getByLabelText("CSV files"), file);
  await userEvent.click(screen.getByRole("button", { name: "Upload" }));

  expect(api.uploadDataset).toHaveBeenCalledWith(file);
  expect(api.createChat).toHaveBeenCalledWith(["abc"]);
  expect(navigateMock).toHaveBeenCalledWith("/c/chat1");
});

test("uploads multiple chosen files, then creates one chat over all of them", async () => {
  vi.spyOn(api, "uploadDataset")
    .mockResolvedValueOnce({ id: "ds1", name: "a.csv", n_rows: 1, n_cols: 1 })
    .mockResolvedValueOnce({ id: "ds2", name: "b.csv", n_rows: 1, n_cols: 1 });
  vi.spyOn(api, "createChat").mockResolvedValue({
    id: "chat1",
    datasets: [{ id: "ds1", name: "a.csv" }, { id: "ds2", name: "b.csv" }],
  });
  renderPage();
  const fileA = new File(["a\n1\n"], "a.csv", { type: "text/csv" });
  const fileB = new File(["b\n2\n"], "b.csv", { type: "text/csv" });

  await userEvent.upload(screen.getByLabelText("CSV files"), [fileA, fileB]);
  await userEvent.click(screen.getByRole("button", { name: "Upload" }));

  expect(api.uploadDataset).toHaveBeenNthCalledWith(1, fileA);
  expect(api.uploadDataset).toHaveBeenNthCalledWith(2, fileB);
  expect(api.createChat).toHaveBeenCalledWith(["ds1", "ds2"]);
  expect(navigateMock).toHaveBeenCalledWith("/c/chat1");
});

test("shows a banner and does not navigate when upload fails", async () => {
  vi.spyOn(api, "uploadDataset").mockRejectedValue(
    new api.ApiError(400, "Only .csv files are accepted"),
  );
  renderPage();
  const file = new File(["x"], "s.csv", { type: "text/csv" });

  await userEvent.upload(screen.getByLabelText("CSV files"), file);
  await userEvent.click(screen.getByRole("button", { name: "Upload" }));

  expect(await screen.findByRole("alert")).toHaveTextContent("Only .csv files are accepted");
  expect(navigateMock).not.toHaveBeenCalled();
});

test("shows a banner and does not navigate when chat creation fails", async () => {
  vi.spyOn(api, "uploadDataset").mockResolvedValue({
    id: "abc", name: "s.csv", n_rows: 3, n_cols: 2,
  });
  vi.spyOn(api, "createChat").mockRejectedValue(new api.ApiError(500, "Server error"));
  renderPage();
  const file = new File(["a,b\n1,2\n"], "s.csv", { type: "text/csv" });

  await userEvent.upload(screen.getByLabelText("CSV files"), file);
  await userEvent.click(screen.getByRole("button", { name: "Upload" }));

  expect(await screen.findByRole("alert")).toHaveTextContent("Server error");
  expect(navigateMock).not.toHaveBeenCalled();
});
