import { Http } from "./http.js";
import type { ChatEvent, ChatResponse } from "./types.js";

function toChat(payload: Record<string, unknown>): ChatResponse {
  return {
    answer: String(payload.answer ?? ""),
    queryId: payload.query_id ? String(payload.query_id) : undefined,
    conversationId: payload.conversation_id
      ? String(payload.conversation_id)
      : undefined,
    model: payload.model ? String(payload.model) : undefined,
    sources: Array.isArray(payload.sources)
      ? (payload.sources as Record<string, unknown>[])
      : [],
    usage: (payload.usage as Record<string, number>) ?? {},
    raw: payload,
  };
}

export class ChatResource {
  constructor(private readonly http: Http) {}

  async create(message: string, extra: Record<string, unknown> = {}): Promise<ChatResponse> {
    const payload = (await this.http.request("POST", "/rag/query", {
      query: message,
      ...extra,
    })) as Record<string, unknown>;
    return toChat(payload);
  }

  async *stream(
    message: string,
    extra: Record<string, unknown> = {}
  ): AsyncGenerator<ChatEvent> {
    for await (const ev of this.http.streamSse("/rag/query/stream", {
      query: message,
      ...extra,
    })) {
      let data: unknown = ev.data;
      try {
        data = JSON.parse(ev.data);
      } catch {
        /* keep string */
      }
      yield { event: ev.event, data };
    }
  }
}

export class AgentsResource {
  constructor(private readonly http: Http) {}

  run(agentId: string, message: string, extra: Record<string, unknown> = {}) {
    return this.http.request("POST", `/agents/${agentId}/run`, {
      message,
      ...extra,
    });
  }
}

export class ConnectorsResource {
  constructor(private readonly http: Http) {}

  list() {
    return this.http.request("GET", "/connectors");
  }

  create(name: string, type: string, extra: Record<string, unknown> = {}) {
    return this.http.request("POST", "/connectors", { name, type, ...extra });
  }
}

export class UsageResource {
  constructor(private readonly http: Http) {}

  get(days = 30) {
    return this.http.request("GET", `/billing/usage?days=${days}`);
  }
}

export class RagResource {
  constructor(private readonly http: Http) {}

  query(message: string, extra: Record<string, unknown> = {}) {
    return this.http.request("POST", "/rag/query", { query: message, ...extra });
  }
}
