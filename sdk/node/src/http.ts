import { errorFromResponse } from "./errors.js";

export type HttpOptions = {
  apiKey: string;
  baseUrl: string;
  timeout: number;
  maxRetries: number;
  fetchImpl: typeof fetch;
};

function backoff(attempt: number): number {
  return Math.min(2 ** attempt * 250, 8000);
}

async function parseBody(res: Response): Promise<unknown> {
  const text = await res.text();
  if (!text) return {};
  try {
    return JSON.parse(text);
  } catch {
    return { message: text };
  }
}

export class Http {
  constructor(private readonly opts: HttpOptions) {}

  async request(
    method: string,
    path: string,
    json?: unknown
  ): Promise<unknown> {
    const url = `${this.opts.baseUrl.replace(/\/$/, "")}${path}`;
    const headers: Record<string, string> = {
      Authorization: `Bearer ${this.opts.apiKey}`,
      "Content-Type": "application/json",
    };
    if (["POST", "PUT", "PATCH"].includes(method.toUpperCase())) {
      headers["Idempotency-Key"] = crypto.randomUUID();
    }

    let attempt = 0;
    while (true) {
      const controller = new AbortController();
      const timer = setTimeout(() => controller.abort(), this.opts.timeout * 1000);
      let res: Response;
      try {
        res = await this.opts.fetchImpl(url, {
          method,
          headers,
          body: json === undefined ? undefined : JSON.stringify(json),
          signal: controller.signal,
        });
      } catch (err) {
        clearTimeout(timer);
        if (attempt >= this.opts.maxRetries) {
          throw err;
        }
        attempt += 1;
        await new Promise((r) => setTimeout(r, backoff(attempt)));
        continue;
      }
      clearTimeout(timer);

      if ([429, 500, 502, 503, 504].includes(res.status)) {
        if (attempt >= this.opts.maxRetries) {
          throw errorFromResponse(res.status, await parseBody(res));
        }
        const retryAfter = res.headers.get("Retry-After");
        const delay = retryAfter && /^\d+$/.test(retryAfter)
          ? Number(retryAfter) * 1000
          : backoff(attempt + 1);
        attempt += 1;
        await new Promise((r) => setTimeout(r, delay));
        continue;
      }

      const body = await parseBody(res);
      if (!res.ok) throw errorFromResponse(res.status, body);
      return body;
    }
  }

  async *streamSse(path: string, json?: unknown): AsyncGenerator<{ event: string; data: string }> {
    const url = `${this.opts.baseUrl.replace(/\/$/, "")}${path}`;
    const res = await this.opts.fetchImpl(url, {
      method: "POST",
      headers: {
        Authorization: `Bearer ${this.opts.apiKey}`,
        "Content-Type": "application/json",
        Accept: "text/event-stream",
        "Idempotency-Key": crypto.randomUUID(),
      },
      body: JSON.stringify(json ?? {}),
    });
    if (!res.ok || !res.body) {
      throw errorFromResponse(res.status, await parseBody(res));
    }
    const reader = res.body.getReader();
    const decoder = new TextDecoder();
    let buffer = "";
    let event = "message";
    let dataLines: string[] = [];
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      const parts = buffer.split("\n");
      buffer = parts.pop() ?? "";
      for (const line of parts) {
        if (line.startsWith("event:")) event = line.slice(6).trim();
        else if (line.startsWith("data:")) dataLines.push(line.slice(5).trimStart());
        else if (line === "") {
          if (dataLines.length) {
            yield { event, data: dataLines.join("\n") };
          }
          event = "message";
          dataLines = [];
        }
      }
    }
  }
}
