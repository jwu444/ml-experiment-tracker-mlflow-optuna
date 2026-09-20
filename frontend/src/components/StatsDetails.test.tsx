import { describe, it, expect, vi, afterEach } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import StatsDetails from "./StatsDetails";

describe("StatsDetails", () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("renders nothing when there are no stats", () => {
    const { container } = render(<StatsDetails stats={[]} />);
    expect(container).toBeEmptyDOMElement();
  });

  it("shows the raw statistics disclosure and a download button", () => {
    render(<StatsDetails stats={[{ mean: 1 }]} />);
    expect(screen.getByText("Raw statistics")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Download JSON" })).toBeInTheDocument();
  });

  it("downloads the stats as a JSON blob when the button is clicked", async () => {
    const createObjectURL = vi.fn((_blob: Blob) => "blob:mock-url");
    const revokeObjectURL = vi.fn();
    // jsdom implements neither of these — provide them for this test.
    Object.assign(URL, { createObjectURL, revokeObjectURL });
    const click = vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => {});

    const stats = [{ column: "age", mean: 42 }];
    render(<StatsDetails stats={stats} />);
    await userEvent.click(screen.getByRole("button", { name: "Download JSON" }));

    expect(createObjectURL).toHaveBeenCalledTimes(1);
    const blob = createObjectURL.mock.calls[0][0];
    expect(blob).toBeInstanceOf(Blob);
    expect(blob.type).toBe("application/json");
    expect(click).toHaveBeenCalledTimes(1);
    expect(revokeObjectURL).toHaveBeenCalledWith("blob:mock-url");
  });
});
