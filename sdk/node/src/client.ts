import { Http } from "./http.js";
import {
  AgentsResource,
  ChatResource,
  ConnectorsResource,
  RagResource,
  UsageResource,
} from "./resources.js";
import type { ChatEvent, ChatResponse, ZentOptions } from "./types.js";

function defaultBaseUrl(): string {
  return process.env.ZENT_BASE_URL || "http://localhost:8000/api/v1";
}

export type ChatCallable = {
  (message: string, extra?: Record<string, unknown>): Promise<ChatResponse>;
  stream(
    message: string,
    extra?: Record<string, unknown>
  ): AsyncGenerator<ChatEvent>;
  create: ChatResource["create"];
};

export class Zent {
  readonly chat: ChatCallable;
  readonly rag: RagResource;
  readonly agents: AgentsResource;
  readonly connectors: ConnectorsResource;
  readonly usage: UsageResource;

  constructor(opts: ZentOptions) {
    const http = new Http({
      apiKey: opts.apiKey,
      baseUrl: opts.baseUrl ?? defaultBaseUrl(),
      timeout: opts.timeout ?? 60,
      maxRetries: opts.maxRetries ?? 3,
      fetchImpl: opts.fetch ?? fetch,
    });
    const chatResource = new ChatResource(http);
    const chat = Object.assign(
      (message: string, extra: Record<string, unknown> = {}) =>
        chatResource.create(message, extra),
      {
        stream: (message: string, extra: Record<string, unknown> = {}) =>
          chatResource.stream(message, extra),
        create: chatResource.create.bind(chatResource),
      }
    );
    this.chat = chat;
    this.rag = new RagResource(http);
    this.agents = new AgentsResource(http);
    this.connectors = new ConnectorsResource(http);
    this.usage = new UsageResource(http);
  }
}
