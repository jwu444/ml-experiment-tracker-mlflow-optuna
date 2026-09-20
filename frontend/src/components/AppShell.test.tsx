import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { vi, beforeEach } from "vitest";
import { MemoryRouter } from "react-router-dom";
import { ThemeProvider } from "../theme";
import AppShell from "./AppShell";
import * as api from "../api";

beforeEach(() => {
  vi.restoreAllMocks();
  localStorage.clear();
  // The rail fetches both lists on mount; unmocked they would hit `fetch`.
  vi.spyOn(api, "listDatasets").mockResolvedValue([]);
  vi.spyOn(api, "listExperiments").mockResolvedValue([]);
});

function renderShell(ui: React.ReactNode, right?: React.ReactNode) {
  render(
    <ThemeProvider>
      <MemoryRouter>
        <AppShell topbarRight={right}>{ui}</AppShell>
      </MemoryRouter>
    </ThemeProvider>,
  );
}

test("renders the brand, the theme toggle, a right slot, and its children", () => {
  renderShell(<p>page body</p>, <span>chips</span>);
  expect(screen.getByText("CSV Analysis")).toBeInTheDocument();
  expect(screen.getByRole("button", { name: /theme/i })).toBeInTheDocument();
  expect(screen.getByText("chips")).toBeInTheDocument();
  expect(screen.getByText("page body")).toBeInTheDocument();
});

test("all navigation lives in the rail; the topbar keeps only the brand", () => {
  renderShell(<p>body</p>);
  // Sections used to be a flat row of links in the topbar *beside* a sidebar that
  // listed datasets regardless of section. There is now one nav surface, and the
  // brand is the only link left up top.
  expect(screen.getByRole("navigation", { name: "Sections" })).toBeInTheDocument();
  const topbarLinks = within(screen.getByRole("banner")).getAllByRole("link");
  expect(topbarLinks.map((a) => a.getAttribute("href"))).toEqual(["/"]);
});

test("exposes the width variant on its main region", () => {
  render(
    <ThemeProvider>
      <MemoryRouter>
        <AppShell width="upload">x</AppShell>
      </MemoryRouter>
    </ThemeProvider>,
  );
  expect(screen.getByRole("main")).toHaveAttribute("data-width", "upload");
});

test("collapsing hides the whole rail and persists to localStorage", async () => {
  renderShell(<p>body</p>);
  expect(screen.getByRole("navigation", { name: "Sections" })).toBeInTheDocument();
  await userEvent.click(screen.getByRole("button", { name: /hide navigation/i }));
  expect(screen.queryByRole("navigation", { name: "Sections" })).not.toBeInTheDocument();
  expect(localStorage.getItem("wp-sidebar")).toBe("collapsed");
});
