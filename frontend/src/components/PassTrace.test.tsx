import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import PassTrace from "./PassTrace";
import type { MessageTraceOut } from "../types";

function trace(): MessageTraceOut {
  return {
    passes: [
      {
        pass_no: 1,
        analyst: {
          model: "claude-sonnet-5", tokens_in: 100, tokens_out: 50,
          latency_ms: 1200, cost_usd: 0.0021, interpretation: "Ages skew young.",
        },
        charts: ["iVBORw0KGgo="],
        stats: [],
        errors: [],
        judge: {
          model: "claude-sonnet-5", tokens_in: 80, tokens_out: 20,
          latency_ms: 600, cost_usd: 0.0009, score: 62,
          feedback: "Add the median.", gaps: ["median missing"],
        },
        revision_instruction: "Include the median.",
      },
      {
        pass_no: 2,
        analyst: {
          model: "claude-sonnet-5", tokens_in: 120, tokens_out: 60,
          latency_ms: 1300, cost_usd: 0.0024, interpretation: "Median age is 28.",
        },
        charts: [],
        stats: [],
        errors: [],
        judge: {
          model: "claude-sonnet-5", tokens_in: 70, tokens_out: 10,
          latency_ms: 500, cost_usd: 0.0007, score: 88,
          feedback: "Good.", gaps: [],
        },
        revision_instruction: "",
      },
    ],
  };
}

test("renders nothing when there is no trace", () => {
  const { container } = render(<PassTrace trace={null} />);
  expect(container).toBeEmptyDOMElement();
});

test("renders nothing for an empty pass list", () => {
  const { container } = render(<PassTrace trace={{ passes: [] }} />);
  expect(container).toBeEmptyDOMElement();
  // The disclosure itself must not appear when there is nothing to show.
  expect(screen.queryByText(/Loop trace/)).not.toBeInTheDocument();
});

test("is collapsed by default and expands on click", async () => {
  const { container } = render(<PassTrace trace={trace()} />);
  const outer = container.querySelector("details") as HTMLDetailsElement;
  expect(outer.open).toBe(false);
  await userEvent.click(screen.getByText(/Loop trace \(2 passes\)/));
  expect(outer.open).toBe(true);
});

test("summarizes the number of passes and shows each pass's judge score", async () => {
  render(<PassTrace trace={trace()} />);
  await userEvent.click(screen.getByText(/Loop trace \(2 passes\)/));
  expect(screen.getByText(/Pass 1/)).toBeInTheDocument();
  expect(screen.getByText(/62/)).toBeInTheDocument();
  expect(screen.getByText(/Pass 2/)).toBeInTheDocument();
  expect(screen.getByText(/88/)).toBeInTheDocument();
});

test("reveals analyst interpretation, judge feedback, and the demoted cost meta when a pass is expanded", async () => {
  const { container } = render(<PassTrace trace={trace()} />);
  await userEvent.click(screen.getByText(/Loop trace \(2 passes\)/));
  // The pass block is its own <details>, collapsed until its summary is clicked.
  const passOne = container.querySelectorAll("details")[1] as HTMLDetailsElement;
  expect(passOne.open).toBe(false);
  await userEvent.click(screen.getByText(/Pass 1/));
  expect(passOne.open).toBe(true);
  expect(screen.getByText("Ages skew young.")).toBeInTheDocument();
  expect(screen.getByText(/Add the median\./)).toBeInTheDocument();
  // Demoted meta line still present (tokens / latency / cost).
  expect(screen.getByText(/1200 ms/)).toBeInTheDocument();
});

test("shows the revision instruction fed to the next pass", async () => {
  render(<PassTrace trace={trace()} />);
  await userEvent.click(screen.getByText(/Loop trace \(2 passes\)/));
  await userEvent.click(screen.getByText(/Pass 1/));
  expect(
    screen.getByText(/Revision fed to next pass: Include the median\./),
  ).toBeInTheDocument();
});

test("never renders the system prompt", async () => {
  render(<PassTrace trace={trace()} />);
  await userEvent.click(screen.getByText(/Loop trace \(2 passes\)/));
  await userEvent.click(screen.getByText(/Pass 1/));
  expect(screen.queryByText(/system prompt/i)).not.toBeInTheDocument();
});

test("renders a pass's rendered chart image when a pass is expanded", async () => {
  render(<PassTrace trace={trace()} />);
  await userEvent.click(screen.getByText(/Loop trace \(2 passes\)/));
  await userEvent.click(screen.getByText(/Pass 1/));
  const img = screen.getByRole("img") as HTMLImageElement;
  expect(img.src).toBe("data:image/png;base64,iVBORw0KGgo=");
});

test("shows a failed-judge badge when the score is null", async () => {
  const t = trace();
  t.passes[0].judge.score = null;
  render(<PassTrace trace={t} />);
  await userEvent.click(screen.getByText(/Loop trace/));
  expect(screen.getByText(/judge failed/i)).toBeInTheDocument();
});
