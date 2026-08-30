import {
  createContext,
  useCallback,
  useContext,
  useMemo,
  useState,
  type ReactNode,
} from "react";
import { platformApi } from "./api";

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
  login: (email: string, password: string) => Promise<void>;
  logout: () => void;
};

const PlatformAuthContext = createContext<PlatformAuthValue | null>(null);

export function PlatformAuthProvider({ children }: { children: ReactNode }) {
  const [session, setSession] = useState<PlatformSession | null>(() =>
    loadPlatformSession()
  );

  const logout = useCallback(() => {
    clearPlatformSession();
    setSession(null);
  }, []);

  const login = useCallback(async (email: string, password: string) => {
    const data = await platformApi<{ access_token: string; email?: string }>(
      "/api/v1/auth/platform/login",
      {
        method: "POST",
        body: JSON.stringify({ email, password }),
      }
    );
    const next = { token: data.access_token, email: data.email || email };
    savePlatformSession(next);
    setSession(next);
  }, []);

  const value = useMemo(
    () => ({ session, login, logout }),
    [session, login, logout]
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
