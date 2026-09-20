import { render, screen } from "@testing-library/react";
import ChatTurn from "./ChatTurn";
import type { ChatMessageOut } from "../types";

const base: ChatMessageOut = {
  id: "m1",
  role: "assistant",
  content: "Here is the analysis.",
  charts: [],
  stats: [],
  errors: [],
};

test("renders prose and one img per chart", () => {
  render(<ChatTurn message={{ ...base, charts: ["AAAA", "BBBB"] }} />);
  expect(screen.getByText("Here is the analysis.")).toBeInTheDocument();
  const imgs = screen.getAllByRole("img");
  expect(imgs).toHaveLength(2);
  expect(imgs[0]).toHaveAttribute("src", "data:image/png;base64,AAAA");
});

test("keeps stats collapsed but present", () => {
  render(<ChatTurn message={{ ...base, stats: [{ mean: 1 }] }} />);
  const details = screen.getByText("Raw statistics").closest("details");
  expect(details).not.toBeNull();
  expect((details as HTMLDetailsElement).open).toBe(false);
});

test("renders a warning per error even when a chart rendered", () => {
  render(<ChatTurn message={{ ...base, charts: ["AAAA"], errors: ["bad column x"] }} />);
  expect(screen.getByRole("img")).toBeInTheDocument();
  expect(screen.getByRole("alert")).toHaveTextContent("bad column x");
});

test("renders assistant prose as Markdown", () => {
  render(<ChatTurn message={{ ...base, content: "**bold** and `code` and\n\n- item" }} />);
  expect(screen.getByText("bold").tagName).toBe("STRONG");
  expect(screen.getByText("code").tagName).toBe("CODE");
  expect(screen.getByRole("listitem")).toHaveTextContent("item");
});

test("renders GFM tables in assistant prose", () => {
  const table = "| a | b |\n| - | - |\n| 1 | 2 |";
  render(<ChatTurn message={{ ...base, content: table }} />);
  expect(screen.getByRole("table")).toBeInTheDocument();
  expect(screen.getByRole("columnheader", { name: "a" })).toBeInTheDocument();
});

test("shows user questions verbatim, not as Markdown", () => {
  render(<ChatTurn message={{ ...base, role: "user", content: "**not bold**" }} />);
  expect(screen.getByText("**not bold**")).toBeInTheDocument();
});
