import { afterEach, describe, expect, it, vi } from "vitest";
import { afterLoginPath, api, platformApi } from "./api";
import { ApiError, AUTH_EXPIRED_EVENT } from "./lib/errors";

function jsonResponse(
  body: unknown,
  status = 200,
  headers: Record<string, string> = {}
) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json", ...headers },
  });
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("api() — manejo de errores y headers", () => {
  it("adjunta Authorization Bearer y X-Organization-Id", async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse({ ok: true }));
    vi.stubGlobal("fetch", fetchMock);

    await api("/api/v1/agents", { token: "tok", organizationId: "org-1" });

    const [, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    const headers = new Headers(init.headers);
    expect(headers.get("Authorization")).toBe("Bearer tok");
    expect(headers.get("X-Organization-Id")).toBe("org-1");
  });

  it("agrega Idempotency-Key solo en mutaciones", async () => {
    const fetchMock = vi.fn(() => Promise.resolve(jsonResponse({})));
    vi.stubGlobal("fetch", fetchMock);

    await api("/api/v1/agents", { method: "POST", token: "t", organizationId: "o" });
    await api("/api/v1/agents", { method: "GET", token: "t", organizationId: "o" });

    const postHeaders = new Headers((fetchMock.mock.calls[0] as unknown as [string, RequestInit])[1].headers);
    const getHeaders = new Headers((fetchMock.mock.calls[1] as unknown as [string, RequestInit])[1].headers);
    expect(postHeaders.get("Idempotency-Key")).toBeTruthy();
    expect(getHeaders.get("Idempotency-Key")).toBeNull();
  });

  it("no reintenta automáticamente mutaciones", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValue(jsonResponse({ message: "boom" }, 500));
    vi.stubGlobal("fetch", fetchMock);

    await expect(api("/api/v1/agents", { method: "POST", token: "t", organizationId: "o" })).rejects.toThrow(
      "boom"
    );
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it("reintenta una vez GETs idempotentes con status retryable", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(jsonResponse({ message: "ups" }, 503))
      .mockResolvedValueOnce(jsonResponse({ ok: true }));
    vi.stubGlobal("fetch", fetchMock);

    await expect(api("/api/v1/agents", { token: "t", organizationId: "o" })).resolves.toEqual({ ok: true });
    expect(fetchMock).toHaveBeenCalledTimes(2);
  });

  it("expone ApiError con status y trace id", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        jsonResponse({ message: "detalle" }, 400, { "X-Trace-Id": "trace-123" })
      )
    );
    try {
      await api("/x");
      expect.unreachable();
    } catch (err) {
      expect(err).toBeInstanceOf(ApiError);
      const apiErr = err as ApiError;
      expect(apiErr.status).toBe(400);
      expect(apiErr.traceId).toBe("trace-123");
    }
  });

  it("emite AUTH_EXPIRED_EVENT ante 401", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(jsonResponse({ detail: "expired" }, 401)));
    const listener = vi.fn();
    window.addEventListener(AUTH_EXPIRED_EVENT, listener);
    await expect(api("/api/v1/agents", { token: "t", organizationId: "o" })).rejects.toThrow();
    expect(listener).toHaveBeenCalledTimes(1);
    window.removeEventListener(AUTH_EXPIRED_EVENT, listener);
  });

  it("extrae message, detail y error_code del error", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(jsonResponse({ message: "mensaje" }, 400)));
    await expect(api("/x")).rejects.toThrow("mensaje");

    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(jsonResponse({ detail: "detalle" }, 400)));
    await expect(api("/x")).rejects.toThrow("detalle");

    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(jsonResponse({ detail: { error_code: "E1", message: "m" } }, 400))
    );
    await expect(api("/x")).rejects.toThrow("E1 m");

    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(jsonResponse({ error_code: "E2" }, 400)));
    await expect(api("/x")).rejects.toThrow("E2");
  });

  it("devuelve undefined en 204", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(null, { status: 204 })));
    await expect(api("/x", { method: "DELETE", token: "t", organizationId: "o" })).resolves.toBeUndefined();
  });

  it("platformApi nunca envía X-Organization-Id", async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse({}));
    vi.stubGlobal("fetch", fetchMock);
    await platformApi("/api/v1/platform/metrics", { token: "t" });
    const headers = new Headers((fetchMock.mock.calls[0] as unknown as [string, RequestInit])[1].headers);
    expect(headers.get("X-Organization-Id")).toBeNull();
    expect(headers.get("Authorization")).toBe("Bearer t");
  });
});

describe("afterLoginPath", () => {
  it("manda al chooser cuando el trial aún no eligió modo", () => {
    expect(
      afterLoginPath({
        organizationId: "org-1",
        companyName: "Acme",
        needsStartMode: true,
      })
    ).toBe("/onboarding/start");
  });

  it("manda al dashboard cuando ya hay workspace", () => {
    expect(
      afterLoginPath({
        organizationId: "org-1",
        companyName: "Acme",
        workspaceId: "ws-1",
        needsStartMode: false,
      })
    ).toBe("/");
  });
});