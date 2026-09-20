import { render, screen } from "@testing-library/react";
import { Card, Badge } from "./index";

test("Card renders its children", () => {
  render(<Card>inside</Card>);
  expect(screen.getByText("inside")).toBeInTheDocument();
});

test("Badge renders children and exposes its tone", () => {
  render(<Badge tone="accent">hist</Badge>);
  const el = screen.getByText("hist");
  expect(el).toHaveAttribute("data-tone", "accent");
});

test("Badge defaults to the neutral tone", () => {
  render(<Badge>x</Badge>);
  expect(screen.getByText("x")).toHaveAttribute("data-tone", "neutral");
});
