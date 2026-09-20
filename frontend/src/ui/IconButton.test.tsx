import { render, screen } from "@testing-library/react";
import { IconButton } from "./index";

test("renders an accessible icon button with a required label", () => {
  render(
    <IconButton label="Copy">
      <svg aria-hidden="true">
        <circle cx="50" cy="50" r="40" />
      </svg>
    </IconButton>
  );
  expect(screen.getByRole("button", { name: "Copy" })).toBeInTheDocument();
});
