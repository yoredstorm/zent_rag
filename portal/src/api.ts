const TOKEN_KEY = "rag_portal_token";
const ORG_KEY = "rag_portal_org";
const COMPANY_KEY = "rag_portal_company";
const EMAIL_KEY = "rag_portal_email";
const ROLES_KEY = "rag_portal_roles";
const PERMS_KEY = "rag_portal_permissions";

export type Session = {
  token: string;
  organizationId: string;
  companyName: string;
  email?: string;
  roles?: string[];
  permissions?: string[];
};

export function loadSession(): Session | null {
  const token = localStorage.getItem(TOKEN_KEY);
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
  if (!token || !organizationId) return null;
  return { token, organizationId, companyName, email, roles, permissions };
}

export function saveSession(session: Session) {
  localStorage.setItem(TOKEN_KEY, session.token);
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
}

export function clearSession() {
  localStorage.removeItem(TOKEN_KEY);
  localStorage.removeItem(ORG_KEY);
  localStorage.removeItem("rag_portal_tenant");
  localStorage.removeItem(COMPANY_KEY);
  localStorage.removeItem(EMAIL_KEY);
  localStorage.removeItem(ROLES_KEY);
  localStorage.removeItem(PERMS_KEY);
}

async function parseError(res: Response): Promise<string> {
  try {
    const data = await res.json();
    if (typeof data.message === "string") return data.message;
    if (typeof data.detail === "string") return data.detail;
    if (data.detail && typeof data.detail === "object") {
      const code = typeof data.detail.error_code === "string" ? data.detail.error_code : "";
      const msg = typeof data.detail.message === "string" ? data.detail.message : "";
      return [code, msg].filter(Boolean).join(" ") || res.statusText;
    }
    if (typeof data.error_code === "string") return data.error_code;
    return res.statusText;
  } catch {
    return res.statusText;
  }
}

export const SIGNUP_API_KEY_STORAGE = "zent_signup_api_key";

export async function api<T>(
  path: string,
  options: RequestInit & { token?: string; organizationId?: string } = {}
): Promise<T> {
  const { token, organizationId, headers, ...rest } = options;
  const h = new Headers(headers);
  if (!h.has("Content-Type")) h.set("Content-Type", "application/json");
  if (token) h.set("Authorization", `Bearer ${token}`);
  if (organizationId) h.set("X-Organization-Id", organizationId);
  const method = (rest.method || "GET").toUpperCase();
  if (["POST", "PUT", "PATCH"].includes(method) && !h.has("Idempotency-Key")) {
    h.set("Idempotency-Key", crypto.randomUUID());
  }

  const res = await fetch(path, { ...rest, headers: h });
  if (!res.ok) {
    throw new Error(await parseError(res));
  }
  if (res.status === 204) return undefined as T;
  return res.json() as Promise<T>;
}

/** Control Center client: never sends X-Organization-Id (not a tenant credential). */
export async function platformApi<T>(
  path: string,
  options: RequestInit & { token?: string } = {}
): Promise<T> {
  const { token, headers, ...rest } = options;
  const h = new Headers(headers);
  if (!h.has("Content-Type")) h.set("Content-Type", "application/json");
  if (token) h.set("Authorization", `Bearer ${token}`);
  const res = await fetch(path, { ...rest, headers: h });
  if (!res.ok) {
    throw new Error(await parseError(res));
  }
  if (res.status === 204) return undefined as T;
  return res.json() as Promise<T>;
}
