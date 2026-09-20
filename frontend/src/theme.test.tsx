import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach } from "vitest";
import { ThemeProvider, useTheme } from "./theme";
import { ThemeToggle } from "./ui";

function Probe() {
  const { theme } = useTheme();
  return <span data-testid="theme">{theme}</span>;
}

beforeEach(() => {
  localStorage.clear();
  document.documentElement.removeAttribute("data-theme");
});

test("uses the stored theme and applies it to <html>", () => {
  localStorage.setItem("wp-theme", "dark");
  render(<ThemeProvider><Probe /></ThemeProvider>);
  expect(screen.getByTestId("theme")).toHaveTextContent("dark");
  expect(document.documentElement).toHaveAttribute("data-theme", "dark");
});

test("defaults to light when nothing is stored (matchMedia stub returns no-preference)", () => {
  render(<ThemeProvider><Probe /></ThemeProvider>);
  expect(screen.getByTestId("theme")).toHaveTextContent("light");
});

test("ThemeToggle flips the theme and persists it", async () => {
  render(<ThemeProvider><Probe /><ThemeToggle /></ThemeProvider>);
  await userEvent.click(screen.getByRole("button", { name: /theme/i }));
  expect(screen.getByTestId("theme")).toHaveTextContent("dark");
  expect(localStorage.getItem("wp-theme")).toBe("dark");
  expect(document.documentElement).toHaveAttribute("data-theme", "dark");
});
