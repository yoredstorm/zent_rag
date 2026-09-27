import { afterEach, describe, expect, it, vi } from "vitest";
import { uploadFileWithProgress, type UploadProgressEvent } from "./api";

type XhrProgressEvent = { lengthComputable: boolean; loaded: number; total: number };

class FakeXHR {
  static instances: FakeXHR[] = [];
  upload: { onprogress: ((event: XhrProgressEvent) => void) | null } = { onprogress: null };
  status = 0;
  statusText = "";
  responseText = "";
  withCredentials = false;
  onload: (() => void) | null = null;
  onerror: (() => void) | null = null;
  onabort: (() => void) | null = null;
  method = "";
  url = "";
  headers: Record<string, string> = {};
  aborted = false;

  constructor() {
    FakeXHR.instances.push(this);
  }

  open(method: string, url: string) {
    this.method = method;
    this.url = url;
  }

  setRequestHeader(name: string, value: string) {
    this.headers[name] = value;
  }

  getResponseHeader(name: string) {
    return this.headers[name] ?? null;
  }

  send() {}

  abort() {
    this.aborted = true;
    this.onabort?.();
  }
}

function form(): FormData {
  const data = new FormData();
  data.append("file", new File(["x"], "a.txt"));
  return data;
}

afterEach(() => {
  FakeXHR.instances = [];
  vi.unstubAllGlobals();
});

describe("uploadFileWithProgress", () => {
  it("sube con headers de sesión, sin Content-Type y con progreso real", async () => {
    vi.stubGlobal("XMLHttpRequest", FakeXHR);
    document.cookie = "rag_csrf=csrf-123";
    const progress: UploadProgressEvent[] = [];
    const promise = uploadFileWithProgress<{ ok: boolean }>("/api/x", form(), {
      token: "tkn",
      organizationId: "org-1",
      onProgress: (event) => progress.push(event),
    });
    const xhr = FakeXHR.instances[0];
    expect(xhr.method).toBe("POST");
    expect(xhr.url).toBe("/api/x");
    expect(xhr.withCredentials).toBe(true);
    expect(xhr.headers.Authorization).toBe("Bearer tkn");
    expect(xhr.headers["X-Organization-Id"]).toBe("org-1");
    expect(xhr.headers["X-Zent-Csrf"]).toBe("csrf-123");
    expect(xhr.headers["Idempotency-Key"]).toBeTruthy();
    expect(xhr.headers["Content-Type"]).toBeUndefined();

    xhr.upload.onprogress?.({ lengthComputable: true, loaded: 5, total: 10 });
    expect(progress).toEqual([{ loaded: 5, total: 10 }]);

    xhr.status = 200;
    xhr.responseText = JSON.stringify({ ok: true });
    xhr.onload?.();
    await expect(promise).resolves.toEqual({ ok: true });
  });

  it("mapea el error del backend a ApiError con su status", async () => {
    vi.stubGlobal("XMLHttpRequest", FakeXHR);
    const promise = uploadFileWithProgress("/api/x", form(), {});
    const xhr = FakeXHR.instances[0];
    xhr.status = 413;
    xhr.statusText = "Payload Too Large";
    xhr.responseText = JSON.stringify({ detail: "File too large (max 25 MB)" });
    xhr.onload?.();
    await expect(promise).rejects.toMatchObject({
      status: 413,
      message: "File too large (max 25 MB)",
    });
  });

  it("reporta error de red y cancelación", async () => {
    vi.stubGlobal("XMLHttpRequest", FakeXHR);
    const network = uploadFileWithProgress("/api/x", form(), {});
    FakeXHR.instances[0].onerror?.();
    await expect(network).rejects.toMatchObject({ status: 0, code: "network_error" });

    const controller = new AbortController();
    const cancelled = uploadFileWithProgress("/api/x", form(), { signal: controller.signal });
    controller.abort();
    await expect(cancelled).rejects.toMatchObject({ code: "aborted" });
  });
});
