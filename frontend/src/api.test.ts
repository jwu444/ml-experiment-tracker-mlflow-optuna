import { describe, it, expect, vi, beforeEach } from "vitest";
import { uploadDataset, getDataset, createChat, getChatHistory, postChat, ApiError } from "./api";

function mockFetch(status: number, body: unknown) {
  return vi.fn().mockResolvedValue({
    ok: status >= 200 && status < 300,
    status,
    statusText: "",
    json: async () => body,
  } as Response);
}

beforeEach(() => {
  vi.restoreAllMocks();
});

describe("api client", () => {
  it("uploadDataset posts multipart FormData to /api/datasets", async () => {
    const fetchMock = mockFetch(200, { id: "abc", name: "s.csv", n_rows: 3, n_cols: 2 });
    vi.stubGlobal("fetch", fetchMock);
    const file = new File(["a,b\n1,2\n"], "s.csv", { type: "text/csv" });

    const result = await uploadDataset(file);

    expect(result.id).toBe("abc");
    const [url, opts] = fetchMock.mock.calls[0];
    expect(url).toBe("/api/datasets");
    expect((opts as RequestInit).method).toBe("POST");
    expect((opts as RequestInit).body).toBeInstanceOf(FormData);
  });

  it("getDataset GETs /api/datasets/{id}", async () => {
    const fetchMock = mockFetch(200, { id: "abc", name: "s.csv", n_rows: 3, n_cols: 2 });
    vi.stubGlobal("fetch", fetchMock);

    const result = await getDataset("abc");

    expect(result.name).toBe("s.csv");
    expect(fetchMock.mock.calls[0][0]).toBe("/api/datasets/abc");
  });

  it("createChat posts dataset_ids to /api/chats", async () => {
    const fetchMock = mockFetch(200, {
      id: "chat1",
      datasets: [{ id: "ds1", name: "a.csv" }, { id: "ds2", name: "b.csv" }],
    });
    vi.stubGlobal("fetch", fetchMock);

    const result = await createChat(["ds1", "ds2"]);

    expect(result.id).toBe("chat1");
    expect(result.datasets).toHaveLength(2);
    const [url, opts] = fetchMock.mock.calls[0];
    expect(url).toBe("/api/chats");
    expect((opts as RequestInit).method).toBe("POST");
    expect(JSON.parse((opts as RequestInit).body as string)).toEqual({
      dataset_ids: ["ds1", "ds2"],
    });
  });

  it("getChatHistory GETs /api/chats/{chatId}", async () => {
    const fetchMock = mockFetch(200, { datasets: [{ id: "ds1", name: "a.csv" }], messages: [] });
    vi.stubGlobal("fetch", fetchMock);

    const result = await getChatHistory("chat1");

    expect(result.messages).toEqual([]);
    expect(result.datasets).toEqual([{ id: "ds1", name: "a.csv" }]);
    expect(fetchMock.mock.calls[0][0]).toBe("/api/chats/chat1");
  });

  it("postChat posts a JSON question to /api/chats/{chatId}/messages", async () => {
    const fetchMock = mockFetch(200, {
      id: "m1", role: "assistant", content: "hi", charts: [], stats: [], errors: [],
    });
    vi.stubGlobal("fetch", fetchMock);

    const result = await postChat("chat1", "why?");

    expect(result.role).toBe("assistant");
    const [url, opts] = fetchMock.mock.calls[0];
    expect(url).toBe("/api/chats/chat1/messages");
    expect((opts as RequestInit).method).toBe("POST");
    expect(JSON.parse((opts as RequestInit).body as string)).toEqual({ question: "why?" });
  });

  it("maps a non-2xx response to a thrown ApiError with detail", async () => {
    const fetchMock = mockFetch(404, { detail: "Chat not found" });
    vi.stubGlobal("fetch", fetchMock);

    await expect(getChatHistory("nope")).rejects.toBeInstanceOf(ApiError);
    vi.stubGlobal("fetch", mockFetch(404, { detail: "Chat not found" }));
    await expect(getChatHistory("nope")).rejects.toMatchObject({
      status: 404,
      message: "Chat not found",
    });
  });
});
