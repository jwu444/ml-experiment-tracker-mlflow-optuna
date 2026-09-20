import { render, screen } from "@testing-library/react";
import DatasetChips from "./DatasetChips";

test("renders nothing when there are no datasets", () => {
  const { container } = render(<DatasetChips datasets={[]} />);
  expect(container).toBeEmptyDOMElement();
});

test("renders one chip per dataset with its name", () => {
  render(
    <DatasetChips
      datasets={[
        { id: "ds1", name: "sales.csv" },
        { id: "ds2", name: "regions.csv" },
      ]}
    />,
  );
  expect(screen.getByText("sales.csv")).toBeInTheDocument();
  expect(screen.getByText("regions.csv")).toBeInTheDocument();
});

test("renders each dataset name as a badge", () => {
  render(<DatasetChips datasets={[{ id: "d1", name: "a.csv" }]} />);
  const chip = screen.getByText("a.csv");
  expect(chip).toHaveAttribute("data-tone"); // Badge sets data-tone
});
