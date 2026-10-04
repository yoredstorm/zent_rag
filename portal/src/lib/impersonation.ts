/**
 * Cambio de pantalla Control Center ⇄ portal de cliente (FASE pruebas).
 *
 * El admin de plataforma entra al portal como usuario vía impersonación
 * (endpoint auditable existente) y vuelve al Control Center con un clic.
 * La sesión de cada espacio vive en su propio storage:
 *  - plataforma: localStorage `rag_platform_token` (persistente)
 *  - portal: sessionStorage `rag_portal_token` (por pestaña)
 * Por eso ambas sesiones pueden coexistir en la misma pestaña y el cambio es
 * solo navegación + escritura de metadatos de impersonación.
 */
import { api, clearSession, loadSession, saveSession, type Session } from "../api";
import { IMPERSONATING_KEY, PLATFORM_TOKEN_KEY } from "../platformAuth";

/** Metadatos no sensibles del banner de impersonación (App.tsx). */
export const IMPERSONATION_META_KEY = "zent_impersonation_meta";

type Navigate = (path: string) => void;

function defaultNavigate(path: string) {
  window.location.assign(path);
}

/** Nombre del tenant impersonado, o null si la sesión actual no es impersonada. */
export function isImpersonating(): string | null {
  if (typeof sessionStorage === "undefined") return null;
  return sessionStorage.getItem(IMPERSONATING_KEY);
}

/** True cuando hay una sesión de plataforma guardada en este navegador. */
export function hasPlatformSession(): boolean {
  if (typeof localStorage === "undefined") return false;
  return Boolean(localStorage.getItem(PLATFORM_TOKEN_KEY));
}

export type EnterTenantOptions = {
  token: string;
  organizationId: string;
  companyName: string;
  email?: string;
  /** Motivo para la auditoría de impersonación (min. 3 caracteres). */
  reason: string;
  expiresSeconds?: number;
  /** Inyectable en tests; por defecto recarga completa a "/". */
  navigate?: Navigate;
};

/**
 * Guarda la sesión impersonada y entra al portal. La recarga completa deja
 * que AuthProvider hidrate roles/permisos/workspace con `/api/v1/auth/me`.
 */
export function enterTenantSession(opts: EnterTenantOptions): void {
  const {
    token,
    organizationId,
    companyName,
    email,
    reason,
    expiresSeconds = 3600,
    navigate = defaultNavigate,
  } = opts;
  const session: Session = { token, organizationId, companyName, email };
  saveSession(session);
  sessionStorage.setItem(IMPERSONATING_KEY, companyName);
  sessionStorage.setItem(
    IMPERSONATION_META_KEY,
    JSON.stringify({
      tenant: companyName,
      reason,
      expiresAt: Math.floor(Date.now() / 1000) + expiresSeconds,
    })
  );
  navigate("/");
}

export type ExitImpersonationOptions = {
  returnTo?: string;
  navigate?: Navigate;
};

/**
 * Revoca la sesión impersonada server-side, limpia el storage del portal y
 * vuelve al Control Center.
 */
export async function exitImpersonationToPlatform(
  opts: ExitImpersonationOptions = {}
): Promise<void> {
  const { returnTo = "/control-center/tenants", navigate = defaultNavigate } = opts;
  const current = loadSession();
  if (current?.token) {
    await api("/api/v1/auth/impersonation/exit", {
      method: "POST",
      token: current.token,
      organizationId: current.organizationId,
    }).catch(() => undefined);
  }
  sessionStorage.removeItem(IMPERSONATING_KEY);
  sessionStorage.removeItem(IMPERSONATION_META_KEY);
  clearSession();
  navigate(returnTo);
}

/**
 * Cierra la sesión de cliente (logout server-side best-effort) sin tocar la de
 * plataforma. Útil para dejar el portal limpio antes de una nueva prueba.
 */
export async function closeTenantSession(): Promise<void> {
  const current = loadSession();
  if (current?.token) {
    await api("/api/v1/auth/logout", {
      method: "POST",
      token: current.token,
      organizationId: current.organizationId,
    }).catch(() => undefined);
  }
  sessionStorage.removeItem(IMPERSONATING_KEY);
  sessionStorage.removeItem(IMPERSONATION_META_KEY);
  clearSession();
}
