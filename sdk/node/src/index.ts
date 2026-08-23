import { Zent } from "./client.js";

export { Zent } from "./client.js";
export {
  APIError,
  AuthenticationError,
  PermissionDeniedError,
  RateLimitError,
} from "./errors.js";
export type { ChatEvent, ChatResponse, ZentOptions } from "./types.js";

export function chat(
  message: string,
  opts: { apiKey: string; baseUrl?: string }
): Promise<import("./types.js").ChatResponse> {
  return new Zent(opts).chat.create(message);
}
