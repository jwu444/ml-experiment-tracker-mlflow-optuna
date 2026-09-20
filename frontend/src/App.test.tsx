import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import App from "./App";
import { ThemeProvider } from "./theme";

test("renders the upload page at /", () => {
  render(
    <ThemeProvider>
      <MemoryRouter initialEntries={["/"]}>
        <App />
      </MemoryRouter>
    </ThemeProvider>,
  );
  expect(screen.getByRole("heading", { name: "CSV Analysis Assistant" })).toBeInTheDocument();
});
