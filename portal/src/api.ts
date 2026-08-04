const TOKEN_KEY = "rag_portal_token";
const TENANT_KEY = "rag_portal_tenant";
const COMPANY_KEY = "rag_portal_company";

export type Session = {
  token: string;
  tenantId: string;
  companyName: string;
};

export function loadSession(): Session | null {
  const token = localStorage.getItem(TOKEN_KEY);
  const tenantId = localStorage.getItem(TENANT_KEY);
  const companyName = localStorage.getItem(COMPANY_KEY) || "";
  if (!token || !tenantId) return null;
  return { token, tenantId, companyName };
}

export function saveSession(session: Session) {
  localStorage.setItem(TOKEN_KEY, session.token);
  localStorage.setItem(TENANT_KEY, session.tenantId);
  localStorage.setItem(COMPANY_KEY, session.companyName);
}

export function clearSession() {
  localStorage.removeItem(TOKEN_KEY);
  localStorage.removeItem(TENANT_KEY);
  localStorage.removeItem(COMPANY_KEY);
}

async function parseError(res: Response): Promise<string> {
  try {
    const data = await res.json();
    return data.message || data.detail || data.error_code || res.statusText;
  } catch {
    return res.statusText;
  }
}

export async function api<T>(
  path: string,
  options: RequestInit & { token?: string; tenantId?: string } = {}
): Promise<T> {
  const { token, tenantId, headers, ...rest } = options;
  const h = new Headers(headers);
  h.set("Content-Type", "application/json");
  if (token) h.set("Authorization", `Bearer ${token}`);
  if (tenantId) h.set("X-Tenant-Id", tenantId);

  const res = await fetch(path, { ...rest, headers: h });
  if (!res.ok) {
    throw new Error(await parseError(res));
  }
  if (res.status === 204) return undefined as T;
  return res.json() as Promise<T>;
}
