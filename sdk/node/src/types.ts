export type ChatResponse = {
  answer: string;
  queryId?: string;
  conversationId?: string;
  model?: string;
  sources: Record<string, unknown>[];
  usage: Record<string, number>;
  raw: Record<string, unknown>;
};

export type ChatEvent = {
  event: string;
  data: unknown;
};

export type ZentOptions = {
  apiKey: string;
  baseUrl?: string;
  timeout?: number;
  maxRetries?: number;
  fetch?: typeof fetch;
};
