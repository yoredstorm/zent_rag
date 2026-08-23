export class APIError extends Error {
  readonly statusCode?: number;
  readonly errorCode?: string;

  constructor(message: string, statusCode?: number, errorCode?: string) {
    super(message);
    this.name = "APIError";
    this.statusCode = statusCode;
    this.errorCode = errorCode;
  }
}

export class AuthenticationError extends APIError {
  constructor(message: string, errorCode?: string) {
    super(message, 401, errorCode);
    this.name = "AuthenticationError";
  }
}

export class PermissionDeniedError extends APIError {
  constructor(message: string, errorCode?: string) {
    super(message, 403, errorCode);
    this.name = "PermissionDeniedError";
  }
}

export class RateLimitError extends APIError {
  constructor(message: string, errorCode?: string) {
    super(message, 429, errorCode);
    this.name = "RateLimitError";
  }
}

export function errorFromResponse(status: number, body: unknown): APIError {
  const payload = (body && typeof body === "object" ? body : {}) as {
    message?: string;
    detail?: string;
    error_code?: string;
  };
  const message = payload.message || payload.detail || `HTTP ${status}`;
  if (status === 401) return new AuthenticationError(message, payload.error_code);
  if (status === 403) return new PermissionDeniedError(message, payload.error_code);
  if (status === 429) return new RateLimitError(message, payload.error_code);
  return new APIError(message, status, payload.error_code);
}
