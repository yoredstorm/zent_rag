import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from "react";
import { platformApi } from "./api";
import { AUTH_EXPIRED_EVENT } from "./lib/errors";

const TOKEN_KEY = "rag_platform_token";
const EMAIL_KEY = "rag_platform_email";
export const IMPERSONATING_KEY = "rag_impersonating";

export type PlatformSession = {
  token: string;
  email: string;
};

function loadPlatformSession(): PlatformSession | null {
  const token = localStorage.getItem(TOKEN_KEY);
  const email = localStorage.getItem(EMAIL_KEY) || "";
  if (!token) return null;
  return { token, email };
}

function savePlatformSession(session: PlatformSession) {
  localStorage.setItem(TOKEN_KEY, session.token);
  localStorage.setItem(EMAIL_KEY, session.email);
}

function clearPlatformSession() {
  localStorage.removeItem(TOKEN_KEY);
  localStorage.removeItem(EMAIL_KEY);
}

type PlatformAuthValue = {
  session: PlatformSession | null;
  login: (
    email: string,
    password: string
  ) => Promise<{ mfaRequired: boolean; mfaSession?: string } | void>;
  loginMfa: (mfaSession: string, code: string) => Promise<void>;
  /** FASE 08: confirma MFA y renueva la sesión de plataforma (step-up). */
  stepUp: (code: string) => Promise<void>;
  logout: () => void;
};

const PlatformAuthContext = createContext<PlatformAuthValue | null>(null);

export function PlatformAuthProvider({ children }: { children: ReactNode }) {
  const [session, setSession] = useState<PlatformSession | null>(() =>
    loadPlatformSession()
  );

  // Forced logout de plataforma ante 401 (scope platform).
  useEffect(() => {
    function onAuthExpired(event: Event) {
      const detail = (event as CustomEvent<{ scope?: string }>).detail;
      if (detail?.scope && detail.scope !== "platform") return;
      clearPlatformSession();
      setSession(null);
    }
    window.addEventListener(AUTH_EXPIRED_EVENT, onAuthExpired);
    return () => window.removeEventListener(AUTH_EXPIRED_EVENT, onAuthExpired);
  }, []);

  const logout = useCallback(() => {
    const current = loadPlatformSession();
    if (current?.token) {
      // Revocar server-side (FASE 06): la cookie HttpOnly se limpia en el servidor.
      void platformApi("/api/v1/auth/logout", {
        method: "POST",
        token: current.token,
      }).catch(() => undefined);
    }
    clearPlatformSession();
    setSession(null);
  }, []);

  const login = useCallback(async (email: string, password: string) => {
    const data = await platformApi<{
      access_token?: string;
      mfa_required?: boolean;
      mfa_session?: string;
      email?: string;
    }>("/api/v1/auth/platform/login", {
      method: "POST",
      body: JSON.stringify({ email, password }),
    });
    if (data.mfa_required) {
      return { mfaRequired: true, mfaSession: data.mfa_session };
    }
    const next = { token: data.access_token || "", email: data.email || email };
    savePlatformSession(next);
    setSession(next);
    return undefined;
  }, []);

  const loginMfa = useCallback(async (mfaSession: string, code: string) => {
    const data = await platformApi<{ access_token: string; email?: string }>(
      "/api/v1/auth/platform/login/mfa",
      {
        method: "POST",
        body: JSON.stringify({ mfa_session: mfaSession, code }),
      }
    );
    const next = { token: data.access_token, email: data.email || "" };
    savePlatformSession(next);
    setSession(next);
  }, []);

  const stepUp = useCallback(async (code: string) => {
    const data = await platformApi<{ access_token: string; step_up?: boolean }>(
      "/api/v1/auth/platform/step-up",
      {
        method: "POST",
        body: JSON.stringify({ code }),
      }
    );
    const current = loadPlatformSession();
    const next = { token: data.access_token, email: current?.email || "" };
    savePlatformSession(next);
    setSession(next);
  }, []);

  const value = useMemo(
    () => ({ session, login, loginMfa, stepUp, logout }),
    [session, login, loginMfa, stepUp, logout]
  );
  return (
    <PlatformAuthContext.Provider value={value}>
      {children}
    </PlatformAuthContext.Provider>
  );
}

export function usePlatformAuth() {
  const ctx = useContext(PlatformAuthContext);
  if (!ctx) {
    throw new Error("usePlatformAuth must be used within PlatformAuthProvider");
  }
  return ctx;
}
