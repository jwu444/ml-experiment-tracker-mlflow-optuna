import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { vi } from "vitest";
import { Button } from "./index";

test("renders children and fires onClick when enabled", async () => {
  const onClick = vi.fn();
  render(<Button onClick={onClick}>Send</Button>);
  await userEvent.click(screen.getByRole("button", { name: "Send" }));
  expect(onClick).toHaveBeenCalledOnce();
});

test("loading disables the button, marks it busy, and suppresses clicks", async () => {
  const onClick = vi.fn();
  render(
    <Button loading onClick={onClick}>
      Send
    </Button>,
  );
  const btn = screen.getByRole("button", { name: "Send" });
  expect(btn).toBeDisabled();
  expect(btn).toHaveAttribute("aria-busy", "true");
  await userEvent.click(btn);
  expect(onClick).not.toHaveBeenCalled();
});

test("exposes variant and size as data attributes", () => {
  render(
    <Button variant="ghost" size="sm">
      X
    </Button>,
  );
  const btn = screen.getByRole("button", { name: "X" });
  expect(btn).toHaveAttribute("data-variant", "ghost");
  expect(btn).toHaveAttribute("data-size", "sm");
});

test("preserves a caller-supplied className alongside the base class", () => {
  render(<Button className="custom">X</Button>);
  expect(screen.getByRole("button", { name: "X" })).toHaveClass("custom");
});
