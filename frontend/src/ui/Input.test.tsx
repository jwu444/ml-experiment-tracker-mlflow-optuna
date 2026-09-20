import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { createRef } from "react";
import { vi } from "vitest";
import { Input, Textarea } from "./index";

describe("Input", () => {
  it("accepts input and calls onChange handler", async () => {
    const onChange = vi.fn();
    render(<Input aria-label="name" onChange={onChange} />);
    const el = screen.getByLabelText("name");
    expect(el).toBeInstanceOf(HTMLInputElement);

    const user = userEvent.setup();
    await user.type(el, "hello");
    expect(onChange).toHaveBeenCalled();
  });

  it("forwards ref", () => {
    const ref = createRef<HTMLInputElement>();
    render(<Input aria-label="name" ref={ref} />);
    const el = screen.getByLabelText("name");
    expect(ref.current).toBe(el);
  });
});

test("Textarea renders with its accessible label", () => {
  render(<Textarea aria-label="Question" />);
  expect(screen.getByLabelText("Question")).toBeInTheDocument();
});
