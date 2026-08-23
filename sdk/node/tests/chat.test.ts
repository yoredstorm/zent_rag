import { describe, expect, it, vi } from "vitest";
import { AuthenticationError, Zent } from "../src/index.ts";

function jsonResponse(status: number, body: unknown, headers: Record<string, string> = {}) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json", ...headers },
  });
}

describe("Zent.chat", () => {
  it("returns an answer", async () => {
    const fetchImpl = vi.fn(async () =>
      jsonResponse(200, {
        answer: "hello",
        query_id: "11111111-1111-1111-1111-111111111111",
        sources: [],
        usage: { total_tokens: 2 },
      })
    );
    const client = new Zent({ apiKey: "zent_sk_live_test", fetch: fetchImpl });
    const res = await client.chat("What is our refund policy?");
    expect(res.answer).toBe("hello");
    expect(fetchImpl).toHaveBeenCalledOnce();
    const init = fetchImpl.mock.calls[0][1] as RequestInit;
    const headers = new Headers(init.headers);
    expect(headers.get("Idempotency-Key")).toBeTruthy();
  });

  it("maps 401 to AuthenticationError", async () => {
    const fetchImpl = vi.fn(async () =>
      jsonResponse(401, { error_code: "invalid_token", message: "Invalid or expired API key" })
    );
    const client = new Zent({ apiKey: "bad", fetch: fetchImpl });
    await expect(client.chat("hi")).rejects.toBeInstanceOf(AuthenticationError);
  });

  it("retries 429 then succeeds", async () => {
    const fetchImpl = vi
      .fn()
      .mockResolvedValueOnce(jsonResponse(429, { error_code: "rate_limited", message: "slow" }))
      .mockResolvedValueOnce(jsonResponse(200, { answer: "ok", sources: [], usage: {} }));
    const client = new Zent({ apiKey: "zent_sk_live_test", fetch: fetchImpl, maxRetries: 2 });
    const res = await client.chat("hi");
    expect(res.answer).toBe("ok");
    expect(fetchImpl).toHaveBeenCalledTimes(2);
  });
});
