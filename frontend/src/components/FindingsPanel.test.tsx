import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, expect, test, vi } from "vitest";

import FindingsPanel from "./FindingsPanel";
import * as api from "../api";

function finding(over: Partial<api.Finding> = {}): api.Finding {
  return {
    id: "f1",
    source_type: "eda",
    source_id: "d1",
    text: "## Shape\n\nRevenue is **seasonal**.",
    original_text: "## Shape\n\nRevenue is **seasonal**.",
    status: "draft",
    created_at: "2026-08-12T00:00:00Z",
    ...over,
  };
}

function renderPanel() {
  render(
    <FindingsPanel
      sourceType="eda"
      sourceId="d1"
      title="EDA findings"
      empty="No EDA write-ups yet."
    />,
  );
}

beforeEach(() => {
  vi.restoreAllMocks();
});

test("asks the API for one source's findings rather than filtering a broad fetch", async () => {
  const list = vi.spyOn(api, "listFindings").mockResolvedValue([finding()]);
  renderPanel();

  await screen.findByText("Shape");
  // Narrowing client-side would silently drop everything past the route's
  // limit and render as an empty panel.
  expect(list).toHaveBeenCalledWith({ source_type: "eda", source_id: "d1" });
});

test("renders the write-up as Markdown, not as its source", async () => {
  vi.spyOn(api, "listFindings").mockResolvedValue([finding()]);
  renderPanel();

  expect(await screen.findByRole("heading", { name: "Shape" })).toBeInTheDocument();
  expect(screen.getByText("seasonal").tagName).toBe("STRONG");
});

test("shows the empty message when the source has no findings", async () => {
  vi.spyOn(api, "listFindings").mockResolvedValue([]);
  renderPanel();

  expect(await screen.findByText("No EDA write-ups yet.")).toBeInTheDocument();
});

test("approving an untouched draft sends the status alone", async () => {
  vi.spyOn(api, "listFindings").mockResolvedValue([finding()]);
  const patch = vi.spyOn(api, "updateFinding").mockResolvedValue(finding({ status: "approved" }));
  const user = userEvent.setup();
  renderPanel();

  await user.click(await screen.findByRole("button", { name: "Approve" }));
  expect(patch).toHaveBeenCalledWith("f1", { status: "approved" });
});

test("approving edited text sends the text and the status together (D20)", async () => {
  vi.spyOn(api, "listFindings").mockResolvedValue([finding()]);
  const patch = vi.spyOn(api, "updateFinding").mockResolvedValue(finding({ status: "approved" }));
  const user = userEvent.setup();
  renderPanel();

  await user.click(await screen.findByRole("button", { name: "Edit" }));
  const box = screen.getByLabelText("Edit finding f1");
  // Edit opens over the RAW Markdown — handing the reviewer rendered text
  // would strip the formatting on save with nothing visibly wrong (#49).
  expect(box).toHaveValue("## Shape\n\nRevenue is **seasonal**.");
  await user.clear(box);
  await user.type(box, "checked");

  await user.click(screen.getByRole("button", { name: "Approve" }));
  // One call, both fields: sending `text` on its own is deliberately an edit
  // and not an approval, so a save-then-approve pair would leave the row a
  // draft if the second call failed.
  expect(patch).toHaveBeenCalledWith("f1", {
    text: "checked",
    status: "approved",
  });
});

test("an empty finding cannot be approved, but can be rejected", async () => {
  vi.spyOn(api, "listFindings").mockResolvedValue([finding({ text: "" })]);
  const patch = vi.spyOn(api, "updateFinding").mockResolvedValue(finding());
  const user = userEvent.setup();
  renderPanel();

  // The backend 422s on this; the button says so rather than letting the
  // reviewer discover it as an error banner.
  expect(await screen.findByRole("button", { name: "Approve" })).toBeDisabled();
  await user.click(screen.getByRole("button", { name: "Reject" }));
  expect(patch).toHaveBeenCalledWith("f1", { status: "rejected" });
});

test("refreshKey refetches so a just-generated draft appears in place", async () => {
  const list = vi.spyOn(api, "listFindings").mockResolvedValue([]);
  const { rerender } = render(
    <FindingsPanel
      sourceType="eda"
      sourceId="d1"
      title="EDA findings"
      empty="No EDA write-ups yet."
      refreshKey={0}
    />,
  );
  await screen.findByText("No EDA write-ups yet.");

  list.mockResolvedValue([finding()]);
  rerender(
    <FindingsPanel
      sourceType="eda"
      sourceId="d1"
      title="EDA findings"
      empty="No EDA write-ups yet."
      refreshKey={1}
    />,
  );
  expect(await screen.findByText("Shape")).toBeInTheDocument();
});

test("surfaces a failed update instead of silently leaving the row unchanged", async () => {
  vi.spyOn(api, "listFindings").mockResolvedValue([finding()]);
  vi.spyOn(api, "updateFinding").mockRejectedValue(
    new api.ApiError(422, "cannot approve an empty finding"),
  );
  const user = userEvent.setup();
  renderPanel();

  await user.click(await screen.findByRole("button", { name: "Approve" }));
  await waitFor(() =>
    expect(screen.getByRole("alert")).toHaveTextContent("cannot approve an empty finding"),
  );
});

test("labels a finding whose text has diverged from the generated draft", async () => {
  vi.spyOn(api, "listFindings").mockResolvedValue([
    finding({ text: "reviewer's words", original_text: "the model's words" }),
  ]);
  renderPanel();

  const panel = await screen.findByRole("region", { name: "EDA findings" });
  expect(within(panel).getByText(/edited from the original draft/i)).toBeInTheDocument();
});
