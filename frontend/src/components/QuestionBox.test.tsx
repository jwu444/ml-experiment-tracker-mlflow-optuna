import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, it, expect, vi } from "vitest";
import QuestionBox from "./QuestionBox";

describe("QuestionBox", () => {
  it("renders textarea with aria-label and Ask button", () => {
    const onSubmit = vi.fn();
    render(<QuestionBox onSubmit={onSubmit} pending={false} />);
    expect(screen.getByLabelText("Question")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Ask" })).toBeInTheDocument();
  });

  it("disables textarea and button when pending", () => {
    const onSubmit = vi.fn();
    render(<QuestionBox onSubmit={onSubmit} pending={true} />);
    expect(screen.getByLabelText("Question")).toBeDisabled();
    expect(screen.getByRole("button", { name: "Asking…" })).toBeDisabled();
  });

  it("disables button when input is empty or whitespace-only", () => {
    const onSubmit = vi.fn();
    render(<QuestionBox onSubmit={onSubmit} pending={false} />);
    const button = screen.getByRole("button");
    expect(button).toBeDisabled();
  });

  it("enables button when input has non-whitespace", async () => {
    const onSubmit = vi.fn();
    const user = userEvent.setup();
    render(<QuestionBox onSubmit={onSubmit} pending={false} />);
    const textarea = screen.getByLabelText("Question");
    await user.type(textarea, "test");
    const button = screen.getByRole("button");
    expect(button).toBeEnabled();
  });

  it("trims input and calls onSubmit on form submit", async () => {
    const onSubmit = vi.fn();
    const user = userEvent.setup();
    render(<QuestionBox onSubmit={onSubmit} pending={false} />);
    const textarea = screen.getByLabelText("Question");
    await user.type(textarea, "  hello  ");
    const button = screen.getByRole("button");
    await user.click(button);
    expect(onSubmit).toHaveBeenCalledWith("hello");
  });

  it("clears textarea after successful submit", async () => {
    const onSubmit = vi.fn();
    const user = userEvent.setup();
    render(<QuestionBox onSubmit={onSubmit} pending={false} />);
    const textarea = screen.getByLabelText("Question");
    await user.type(textarea, "hello");
    const button = screen.getByRole("button");
    await user.click(button);
    expect(textarea).toHaveValue("");
  });

  it("submits on Enter and clears the textarea", async () => {
    const onSubmit = vi.fn();
    const user = userEvent.setup();
    render(<QuestionBox onSubmit={onSubmit} pending={false} />);
    const textarea = screen.getByLabelText("Question");
    await user.type(textarea, "hello");
    await user.type(textarea, "{Enter}");
    expect(onSubmit).toHaveBeenCalledWith("hello");
    expect(textarea).toHaveValue("");
  });

  it("inserts a newline on Shift+Enter without submitting", async () => {
    const onSubmit = vi.fn();
    const user = userEvent.setup();
    render(<QuestionBox onSubmit={onSubmit} pending={false} />);
    const textarea = screen.getByLabelText("Question");
    await user.type(textarea, "line one{Shift>}{Enter}{/Shift}line two");
    expect(onSubmit).not.toHaveBeenCalled();
    expect(textarea).toHaveValue("line one\nline two");
  });

  it("does not call onSubmit when pending", async () => {
    const onSubmit = vi.fn();
    const user = userEvent.setup();
    const { rerender } = render(
      <QuestionBox onSubmit={onSubmit} pending={false} />
    );
    const textarea = screen.getByLabelText("Question");
    await user.type(textarea, "hello");
    rerender(<QuestionBox onSubmit={onSubmit} pending={true} />);
    const button = screen.getByRole("button", { name: "Asking…" });
    await user.click(button);
    expect(onSubmit).not.toHaveBeenCalled();
  });
});
