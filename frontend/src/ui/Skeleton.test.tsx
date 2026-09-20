import { render, screen } from "@testing-library/react";
import { Skeleton } from "./index";

test("renders a labelled status region with the requested number of placeholders", () => {
  render(<Skeleton count={3} />);
  const status = screen.getByRole("status", { name: "Loading" });
  expect(status.querySelectorAll("[data-variant]")).toHaveLength(3);
});

test("defaults to a single line placeholder", () => {
  render(<Skeleton />);
  const status = screen.getByRole("status");
  const items = status.querySelectorAll("[data-variant]");
  expect(items).toHaveLength(1);
  expect(items[0]).toHaveAttribute("data-variant", "line");
});
