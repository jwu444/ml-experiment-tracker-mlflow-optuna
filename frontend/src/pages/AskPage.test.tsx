import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

import AskPage from "./AskPage";
import * as api from "../api";
import { ThemeProvider } from "../theme";

function answer(overrides = {}) {
  return {
    answer: "Ridge beat the persistence baseline by 4.2 RMSE.",
    retrieved: [
      {
        source_type: "note" as const,
        source_id: "run-1",
        run_id: "run-1",
        experiment_id: "exp-1",
        dataset_id: "ds-1",
        snippet: "Ridge at alpha=1.0 scored 12.5 RMSE.",
        score: 0.91,
      },
    ],
    warnings: [],
    trace: {
      steps: [
        {
          type: "tool" as const,
          model: "",
          tokens_in: 0,
          tokens_out: 0,
          latency_ms: 8,
          tool_name: "search_runs",
          tool_args: { query: "ridge" },
          result_summary: "1 source(s)",
          error: null,
        },
      ],
      tokens_in: 100,
      tokens_out: 40,
      cost_usd: 0.002,
      latency_ms: 1500,
    },
    ...overrides,
  };
}

function renderPage() {
  // ThemeProvider because the page carries AppShell, and the shell's theme
  // toggle calls useTheme(); the other page tests wrap the same way.
  return render(
    <ThemeProvider>
      <MemoryRouter>
        <AskPage />
      </MemoryRouter>
    </ThemeProvider>,
  );
}

async function ask(text = "which model won?") {
  await userEvent.type(screen.getByLabelText(/question/i), text);
  await userEvent.click(screen.getByRole("button", { name: /^Ask(ing…)?$/ }));
}

describe("AskPage", () => {
  beforeEach(() => vi.restoreAllMocks());

  it("renders the answer", async () => {
    vi.spyOn(api, "askAgent").mockResolvedValue(answer());
    renderPage();
    await ask();
    expect(await screen.findByText(/beat the persistence baseline/i)).toBeInTheDocument();
  });

  it("links a note citation to its experiment", async () => {
    vi.spyOn(api, "askAgent").mockResolvedValue(answer());
    renderPage();
    await ask();
    const link = await screen.findByRole("link", { name: /run-1|ridge|note/i });
    expect(link).toHaveAttribute("href", "/experiments/exp-1");
  });

  it("links an eda citation to its dataset", async () => {
    vi.spyOn(api, "askAgent").mockResolvedValue(
      answer({
        retrieved: [
          {
            source_type: "eda" as const,
            source_id: "ds-1",
            run_id: null,
            experiment_id: null,
            dataset_id: "ds-1",
            snippet: "Revenue is right-skewed.",
            score: 0.8,
          },
        ],
      }),
    );
    renderPage();
    await ask();
    const link = await screen.findByRole("link", { name: /eda|ds-1|revenue/i });
    expect(link).toHaveAttribute("href", "/datasets/ds-1");
  });

  it("says so when nothing was retrieved", async () => {
    vi.spyOn(api, "askAgent").mockResolvedValue(
      answer({ answer: "No reviewed history matches.", retrieved: [] }),
    );
    renderPage();
    await ask();
    expect(await screen.findByText(/no sources/i)).toBeInTheDocument();
  });

  it("shows warnings returned with the answer", async () => {
    vi.spyOn(api, "askAgent").mockResolvedValue(
      answer({ warnings: ["status filter was not applied"] }),
    );
    renderPage();
    await ask();
    expect(await screen.findByText(/status filter was not applied/i)).toBeInTheDocument();
  });

  it("disables Ask while a question is in flight", async () => {
    let resolve!: (value: unknown) => void;
    vi.spyOn(api, "askAgent").mockReturnValue(
      new Promise((r) => {
        resolve = r;
      }) as never,
    );
    renderPage();
    await ask();
    expect(screen.getByRole("button", { name: /^Ask(ing…)?$/ })).toBeDisabled();
    resolve(answer());
    await waitFor(() => expect(screen.getByRole("button", { name: /^Ask(ing…)?$/ })).not.toBeDisabled());
  });

  it("will not submit a blank question", async () => {
    const spy = vi.spyOn(api, "askAgent").mockResolvedValue(answer());
    renderPage();
    await userEvent.click(screen.getByRole("button", { name: /^Ask(ing…)?$/ }));
    expect(spy).not.toHaveBeenCalled();
  });

  it("shows an error banner when the request fails", async () => {
    vi.spyOn(api, "askAgent").mockRejectedValue(new Error("boom"));
    renderPage();
    await ask();
    expect(await screen.findByText(/boom/i)).toBeInTheDocument();
  });

  it("exposes the trace behind a disclosure", async () => {
    vi.spyOn(api, "askAgent").mockResolvedValue(answer());
    renderPage();
    await ask();
    expect(await screen.findByText(/search_runs/i)).toBeInTheDocument();
  });
});
