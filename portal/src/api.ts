import { ApiError, emitAuthExpired, emitStepUpRequired, RETRYABLE_STATUS } from "./lib/errors";

// El token de sesión vive en sessionStorage (no persistente; la sesión real es
// la cookie HttpOnly del servidor, FASE 05). El perfil (no sensible) va en localStorage.
const TOKEN_KEY = "rag_portal_token";
const ORG_KEY = "rag_portal_org";
const COMPANY_KEY = "rag_portal_company";
const EMAIL_KEY = "rag_portal_email";
const ROLES_KEY = "rag_portal_roles";
const PERMS_KEY = "rag_portal_permissions";
const WS_KEY = "rag_portal_workspace";
const WS_KIND_KEY = "rag_portal_workspace_kind";

export type Session = {
  token?: string;
  organizationId: string;
  companyName: string;
  email?: string;
  roles?: string[];
  permissions?: string[];
  workspaceId?: string;
  workspaceKind?: string;
  needsStartMode?: boolean;
};

export function afterLoginPath(session: Session | null): string {
  return session?.needsStartMode ? "/onboarding/start" : "/";
}

function readToken(): string | undefined {
  const current = sessionStorage.getItem(TOKEN_KEY);
  if (current) return current;
  const legacy = localStorage.getItem(TOKEN_KEY);
  if (legacy) {
    // Migración de sesiones previas: mover a sessionStorage.
    sessionStorage.setItem(TOKEN_KEY, legacy);
    localStorage.removeItem(TOKEN_KEY);
    return legacy;
  }
  return undefined;
}

function writeToken(token: string | undefined) {
  if (token) {
    sessionStorage.setItem(TOKEN_KEY, token);
  } else {
    sessionStorage.removeItem(TOKEN_KEY);
  }
  // Nunca persistir el token en localStorage.
  localStorage.removeItem(TOKEN_KEY);
}

/** Token CSRF double-submit (cookie no HttpOnly emitida por el backend). */
export function getCsrfToken(): string | null {
  const match = document.cookie.match(/(?:^|;\s*)rag_csrf=([^;]+)/);
  return match ? decodeURIComponent(match[1]) : null;
}

export function loadSession(): Session | null {
  const organizationId =
    localStorage.getItem(ORG_KEY) ||
    // migración de sesiones previas (tenant)
    localStorage.getItem("rag_portal_tenant");
  const companyName = localStorage.getItem(COMPANY_KEY) || "";
  const email = localStorage.getItem(EMAIL_KEY) || undefined;
  const rolesRaw = localStorage.getItem(ROLES_KEY);
  const permsRaw = localStorage.getItem(PERMS_KEY);
  let roles: string[] | undefined;
  let permissions: string[] | undefined;
  try {
    roles = rolesRaw ? (JSON.parse(rolesRaw) as string[]) : undefined;
    permissions = permsRaw ? (JSON.parse(permsRaw) as string[]) : undefined;
  } catch {
    roles = undefined;
    permissions = undefined;
  }
  if (!organizationId) return null;
  const token = readToken();
  const workspaceId = localStorage.getItem(WS_KEY) || undefined;
  const workspaceKind = localStorage.getItem(WS_KIND_KEY) || undefined;
  return {
    token,
    organizationId,
    companyName,
    email,
    roles,
    permissions,
    workspaceId,
    workspaceKind,
    needsStartMode: !workspaceId,
  };
}

export function saveSession(session: Session) {
  writeToken(session.token);
  localStorage.setItem(ORG_KEY, session.organizationId);
  localStorage.removeItem("rag_portal_tenant");
  localStorage.setItem(COMPANY_KEY, session.companyName);
  if (session.email) {
    localStorage.setItem(EMAIL_KEY, session.email);
  } else {
    localStorage.removeItem(EMAIL_KEY);
  }
  if (session.roles?.length) {
    localStorage.setItem(ROLES_KEY, JSON.stringify(session.roles));
  } else {
    localStorage.removeItem(ROLES_KEY);
  }
  if (session.permissions?.length) {
    localStorage.setItem(PERMS_KEY, JSON.stringify(session.permissions));
  } else {
    localStorage.removeItem(PERMS_KEY);
  }
  if (session.workspaceId) {
    localStorage.setItem(WS_KEY, session.workspaceId);
  } else {
    localStorage.removeItem(WS_KEY);
  }
  if (session.workspaceKind) {
    localStorage.setItem(WS_KIND_KEY, session.workspaceKind);
  } else {
    localStorage.removeItem(WS_KIND_KEY);
  }
}

export function clearSession() {
  sessionStorage.removeItem(TOKEN_KEY);
  localStorage.removeItem(TOKEN_KEY);
  localStorage.removeItem(ORG_KEY);
  localStorage.removeItem("rag_portal_tenant");
  localStorage.removeItem(COMPANY_KEY);
  localStorage.removeItem(EMAIL_KEY);
  localStorage.removeItem(ROLES_KEY);
  localStorage.removeItem(PERMS_KEY);
  localStorage.removeItem(WS_KEY);
  localStorage.removeItem(WS_KIND_KEY);
}

/** Extrae el trace id del backend (TraceMiddleware → X-Trace-Id). */
function traceIdFrom(res: Response): string | null {
  return res.headers.get("X-Trace-Id");
}

async function toApiError(res: Response): Promise<ApiError> {
  const traceId = traceIdFrom(res);
  let code = "";
  let message = "";
  try {
    const data = await res.json();
    if (typeof data.message === "string") message = data.message;
    else if (typeof data.detail === "string") message = data.detail;
    else if (data.detail && typeof data.detail === "object") {
      code = typeof data.detail.error_code === "string" ? data.detail.error_code : "";
      message = typeof data.detail.message === "string" ? data.detail.message : "";
    }
    if (!code && typeof data.error_code === "string") code = data.error_code;
    if (!message) message = res.statusText;
    if (code && message && message !== res.statusText) message = `${code} ${message}`;
    if (!message && code) message = code;
  } catch {
    message = res.statusText;
  }
  return new ApiError(message || res.statusText, res.status, code, traceId);
}

const delay = (ms: number) => new Promise((resolve) => setTimeout(resolve, ms));

// Throttle de auth-expired: evita la estampida de logout/loop cuando N
// requests fallan a la vez con 401 (ej. páginas que cargan en paralelo).
let _lastAuthExpiredAt = 0;
function emitAuthExpiredThrottled(platform: boolean) {
  const now = Date.now();
  if (now - _lastAuthExpiredAt < 5000) return;
  _lastAuthExpiredAt = now;
  emitAuthExpired(platform ? "platform" : "tenant");
}

async function request<T>(
  path: string,
  options: RequestInit & { token?: string; organizationId?: string; workspaceId?: string } = {},
  opts: { safeRetry?: boolean; idempotency?: boolean; platform?: boolean } = {}
): Promise<T> {
  const { token, organizationId, workspaceId, headers, ...rest } = options;
  const h = new Headers(headers);
  if (rest.body instanceof FormData) {
    h.delete("Content-Type");
  } else if (!h.has("Content-Type")) {
    h.set("Content-Type", "application/json");
  }
  if (token) h.set("Authorization", `Bearer ${token}`);
  if (organizationId) h.set("X-Organization-Id", organizationId);
  const resolvedWorkspace = workspaceId || (!opts.platform ? loadSession()?.workspaceId : undefined);
  if (resolvedWorkspace) h.set("X-Workspace-Id", resolvedWorkspace);
  const method = (rest.method || "GET").toUpperCase();
  const platform = opts.platform === true;
  if (opts.idempotency !== false && ["POST", "PUT", "PATCH"].includes(method) && !h.has("Idempotency-Key")) {
    h.set("Idempotency-Key", crypto.randomUUID());
  }
  // CSRF double-submit: cookie no HttpOnly + header (FASE 05/11).
  if (["POST", "PUT", "PATCH", "DELETE"].includes(method) && !h.has("X-Zent-Csrf")) {
    const csrf = getCsrfToken();
    if (csrf) h.set("X-Zent-Csrf", csrf);
  }

  let attempt = 0;
  for (;;) {
    const res = await fetch(path, { ...rest, headers: h, credentials: "same-origin" });
    if (res.ok) {
      if (res.status === 204) return undefined as T;
      return res.json() as Promise<T>;
    }
    const err = await toApiError(res);
    if (err.status === 401) emitAuthExpiredThrottled(platform);
    if (err.status === 403 && err.code === "step_up_required") emitStepUpRequired();
    const canRetry =
      opts.safeRetry === true &&
      attempt < 1 &&
      ["GET", "HEAD"].includes(method) &&
      RETRYABLE_STATUS.includes(err.status);
    if (canRetry) {
      attempt += 1;
      await delay(300 * attempt);
      continue;
    }
    throw err;
  }
}

/** Cliente del Customer Portal (tenant). */
export async function api<T>(
  path: string,
  options: RequestInit & { token?: string; organizationId?: string } = {}
): Promise<T> {
  return request<T>(path, options, { safeRetry: true });
}

/** Cliente del Control Center: nunca envía X-Organization-Id (no es credencial tenant). */
export async function platformApi<T>(
  path: string,
  options: RequestInit & { token?: string } = {}
): Promise<T> {
  return request<T>(path, options, { safeRetry: true, platform: true });
}

export const SIGNUP_API_KEY_STORAGE = "zent_signup_api_key";