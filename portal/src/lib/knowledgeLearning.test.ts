import { afterEach, describe, expect, it, vi } from "vitest";
import { AUTH_EXPIRED_EVENT } from "./errors";
import { fetchLearningStatus, streamRunEvents } from "./knowledgeLearning";

function jsonResponse(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

afterEach(() => {
  vi.unstubAllGlobals();
  window.localStorage.clear();
  window.sessionStorage.clear();
});

describe("knowledge learning API client", () => {
  it("adjunta token y organización de la sesión", async () => {
    window.sessionStorage.setItem("rag_portal_token", "sess-tok");
    window.localStorage.setItem("rag_portal_org", "org-9");
    window.localStorage.setItem("rag_portal_company", "Acme");
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse({ enabled: true }));
    vi.stubGlobal("fetch", fetchMock);

    await fetchLearningStatus();

    const headers = new Headers((fetchMock.mock.calls[0] as [string, RequestInit])[1].headers);
    expect(headers.get("Authorization")).toBe("Bearer sess-tok");
    expect(headers.get("X-Organization-Id")).toBe("org-9");
  });

  it("emite AUTH_EXPIRED_EVENT ante 401 en /knowledge/learning/*", async () => {
    window.sessionStorage.setItem("rag_portal_token", "expired");
    window.localStorage.setItem("rag_portal_org", "org-9");
    window.localStorage.setItem("rag_portal_company", "Acme");
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(jsonResponse({ detail: "expired" }, 401)));
    const listener = vi.fn();
    window.addEventListener(AUTH_EXPIRED_EVENT, listener);

    await expect(fetchLearningStatus()).rejects.toMatchObject({ status: 401 });
    expect(listener).toHaveBeenCalledTimes(1);
    const event = listener.mock.calls[0][0] as CustomEvent<{ scope?: string }>;
    expect(event.detail?.scope).toBe("tenant");

    window.removeEventListener(AUTH_EXPIRED_EVENT, listener);
  });

  it("el stream SSE también fuerza sesión ante 401", async () => {
    window.sessionStorage.setItem("rag_portal_token", "expired");
    window.localStorage.setItem("rag_portal_org", "org-9");
    const listener = vi.fn();
    window.addEventListener(AUTH_EXPIRED_EVENT, listener);
    const onError = vi.fn();
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(new Response(JSON.stringify({ detail: "expired" }), { status: 401 }))
    );

    const handle = streamRunEvents({ runId: "run-1", onEvent: () => {}, onError });
    await vi.waitFor(() => expect(listener).toHaveBeenCalledTimes(1));
    expect(onError).toHaveBeenCalled();
    handle.close();
    window.removeEventListener(AUTH_EXPIRED_EVENT, listener);
  });
});
