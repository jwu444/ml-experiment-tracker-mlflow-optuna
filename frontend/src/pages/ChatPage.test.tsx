import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { vi, beforeEach } from "vitest";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import ChatPage from "./ChatPage";
import * as api from "../api";
import { ThemeProvider } from "../theme";

function renderAt(chatId: string) {
  render(
    <ThemeProvider>
      <MemoryRouter initialEntries={[`/c/${chatId}`]}>
        <Routes>
          <Route path="/c/:chatId" element={<ChatPage />} />
        </Routes>
      </MemoryRouter>
    </ThemeProvider>,
  );
}

beforeEach(() => {
  vi.restoreAllMocks();
  vi.spyOn(api, "listDatasets").mockResolvedValue([]);
});

test("renders attached dataset chips and history", async () => {
  vi.spyOn(api, "getChatHistory").mockResolvedValue({
    datasets: [{ id: "ds1", name: "sales.csv" }, { id: "ds2", name: "regions.csv" }],
    messages: [
      { id: "m1", role: "user", content: "why?", charts: [], stats: [], errors: [] },
      { id: "m2", role: "assistant", content: "because", charts: [], stats: [], errors: [] },
    ],
  });

  renderAt("chat1");

  expect(await screen.findByText("sales.csv")).toBeInTheDocument();
  expect(screen.getByText("regions.csv")).toBeInTheDocument();
  expect(screen.getByText("because")).toBeInTheDocument();
});

test("appends the user turn and the returned assistant turn on ask", async () => {
  vi.spyOn(api, "getChatHistory").mockResolvedValue({
    datasets: [{ id: "ds1", name: "sales.csv" }],
    messages: [],
  });
  vi.spyOn(api, "postChat").mockResolvedValue({
    id: "m9", role: "assistant", content: "The answer.", charts: [], stats: [], errors: [],
  });

  renderAt("chat1");
  await screen.findByText("sales.csv");

  await userEvent.type(screen.getByLabelText("Question"), "why is revenue high?");
  await userEvent.click(screen.getByRole("button", { name: "Ask" }));

  expect(await screen.findByText("The answer.")).toBeInTheDocument();
  expect(screen.getByText("why is revenue high?")).toBeInTheDocument();
  expect(api.postChat).toHaveBeenCalledWith("chat1", "why is revenue high?");
});

test("shows a banner when the initial load fails", async () => {
  vi.spyOn(api, "getChatHistory").mockRejectedValue(new api.ApiError(404, "Chat not found"));

  renderAt("nope");

  expect(await screen.findByRole("alert")).toHaveTextContent("Chat not found");
});

test("shows a loading skeleton before history resolves", () => {
  // history fetch pending: getChatHistory returns a never-resolving promise
  vi.spyOn(api, "getChatHistory").mockReturnValue(new Promise(() => {}));
  renderAt("c1");
  // Scoped to <main>: the sidebar (AppShell) has its own pending-datasets
  // Skeleton with the same role/name, so an unscoped query is ambiguous.
  expect(
    within(screen.getByRole("main")).getByRole("status", { name: "Loading" }),
  ).toBeInTheDocument();
});

test("shows the question while the answer is still being generated (#50)", async () => {
  vi.spyOn(api, "getChatHistory").mockResolvedValue({
    datasets: [{ id: "ds1", name: "sales.csv" }],
    messages: [],
  });
  // Never resolves: the assertions below all describe the in-flight window,
  // which is exactly the window the bug made invisible.
  vi.spyOn(api, "postChat").mockReturnValue(new Promise(() => {}));

  renderAt("chat1");
  await screen.findByText("sales.csv");
  await userEvent.type(screen.getByLabelText("Question"), "why is revenue high?");
  await userEvent.click(screen.getByRole("button", { name: "Ask" }));

  expect(await screen.findByText("why is revenue high?")).toBeInTheDocument();
  expect(screen.getByText(/Sending…/)).toBeInTheDocument();
});

test("marks an optimistic turn as not sent when the request fails (#50)", async () => {
  vi.spyOn(api, "getChatHistory").mockResolvedValue({
    datasets: [{ id: "ds1", name: "sales.csv" }],
    messages: [],
  });
  vi.spyOn(api, "postChat").mockRejectedValue(new api.ApiError(500, "Loop blew up"));

  renderAt("chat1");
  await screen.findByText("sales.csv");
  await userEvent.type(screen.getByLabelText("Question"), "why is revenue high?");
  await userEvent.click(screen.getByRole("button", { name: "Ask" }));

  // The turn stays so the question is not destroyed — QuestionBox has already
  // cleared its input — but it must not claim to have been saved.
  expect(await screen.findByText("why is revenue high?")).toBeInTheDocument();
  expect(screen.getByText(/Not sent/)).toBeInTheDocument();
  expect(screen.queryByText(/Sending…/)).not.toBeInTheDocument();
});

test("keeps every failed turn marked, not just the most recent (#50)", async () => {
  // Sends are serialized, so at most one is ever in flight — but FAILURES are
  // not, and a single `failedTurnId` slot was overwritten by the second one.
  // The first question then re-rendered as delivered while the only copy of it
  // was the row on screen: the exact loss the optimistic turn exists to prevent.
  vi.spyOn(api, "getChatHistory").mockResolvedValue({
    datasets: [{ id: "ds1", name: "sales.csv" }],
    messages: [],
  });
  vi.spyOn(api, "postChat").mockRejectedValue(new api.ApiError(500, "Loop blew up"));

  renderAt("chat1");
  await screen.findByText("sales.csv");
  for (const question of ["first question", "second question"]) {
    await userEvent.type(screen.getByLabelText("Question"), question);
    await userEvent.click(screen.getByRole("button", { name: "Ask" }));
    await screen.findByText(question);
  }

  expect(screen.getAllByText(/Not sent/)).toHaveLength(2);
});

test("distinguishes user turns from assistant turns (#50)", async () => {
  vi.spyOn(api, "getChatHistory").mockResolvedValue({
    datasets: [{ id: "ds1", name: "sales.csv" }],
    messages: [
      { id: "m1", role: "user", content: "why?", charts: [], stats: [], errors: [] },
      { id: "m2", role: "assistant", content: "because", charts: [], stats: [], errors: [] },
    ],
  });

  renderAt("chat1");

  // Vitest runs with `css: false`, so the styling itself cannot be asserted —
  // only that each turn carries the `data-role` hook the stylesheet targets.
  // The CSS gap this fixes was a missing `[data-role="user"]` rule, not a
  // missing attribute, so this guards the contract rather than the appearance.
  const user = (await screen.findByText("why?")).closest("[data-role]");
  const assistant = screen.getByText("because").closest("[data-role]");
  expect(user).toHaveAttribute("data-role", "user");
  expect(assistant).toHaveAttribute("data-role", "assistant");
});

test("shows an empty state when there are no messages", async () => {
  vi.spyOn(api, "getChatHistory").mockResolvedValue({
    datasets: [{ id: "d1", name: "d.csv" }],
    messages: [],
  });
  renderAt("c1");
  expect(await screen.findByText(/Ask your first question/i)).toBeInTheDocument();
});
