/**
 * Taxonomía de errores del API (FASE 13).
 * Todos los errores de red pasan por ApiError con status, código y trace id.
 */

export class ApiError extends Error {
  readonly status: number;
  readonly code: string;
  readonly traceId: string | null;
  readonly retryable: boolean;

  constructor(message: string, status: number, code: string, traceId: string | null) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.code = code;
    this.traceId = traceId;
    this.retryable = [408, 429, 500, 502, 503, 504].includes(status);
  }
}

export const isApiError = (err: unknown): err is ApiError => err instanceof ApiError;

/** 401: la sesión caducó o fue revocada; no pintar ErrorInline genérico. */
export function isUnauthorized(err: unknown): boolean {
  return isApiError(err) && err.status === 401;
}

/** Estados HTTP que justifican reintento seguro (GET/HEAD idempotente).
 *  429 NO: "slow down" — reintentar inmediatamente empeora la carga. */
export const RETRYABLE_STATUS = [408, 500, 502, 503, 504];

export const AUTH_EXPIRED_EVENT = "zent:auth-expired";

/** FASE 08: una operación crítica exigió confirmación MFA reciente. */
export const STEP_UP_REQUIRED_EVENT = "zent:step-up-required";

/** Notifica a los providers de sesión que el token caducó o fue revocado. */
export function emitAuthExpired(scope: "tenant" | "platform" = "tenant") {
  if (typeof window !== "undefined") {
    window.dispatchEvent(new CustomEvent(AUTH_EXPIRED_EVENT, { detail: { scope } }));
  }
}

/** Notifica al Control Center que una operación crítica requiere MFA. */
export function emitStepUpRequired() {
  if (typeof window !== "undefined") {
    window.dispatchEvent(new CustomEvent(STEP_UP_REQUIRED_EVENT));
  }
}