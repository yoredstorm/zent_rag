import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from "react";
import {
  api,
  clearSession,
  loadSession,
  saveSession,
  type Session,
} from "./api";

type AuthContextValue = {
  session: Session | null;
  ready: boolean;
  login: (email: string, password: string) => Promise<void>;
  signup: (
    companyName: string,
    email: string,
    password: string
  ) => Promise<void>;
  logout: () => void;
};

const AuthContext = createContext<AuthContextValue | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [session, setSession] = useState<Session | null>(() => loadSession());
  const [ready, setReady] = useState(false);

  const logout = useCallback(() => {
    clearSession();
    setSession(null);
  }, []);

  useEffect(() => {
    let cancelled = false;
    async function validate() {
      const current = loadSession();
      if (!current) {
        if (!cancelled) setReady(true);
        return;
      }
      try {
        const me = await api<{
          tenant_id: string;
          company_name: string;
          email?: string | null;
        }>("/api/v1/auth/me", {
          token: current.token,
          tenantId: current.tenantId,
        });
        if (cancelled) return;
        const next: Session = {
          token: current.token,
          tenantId: me.tenant_id,
          companyName: me.company_name || current.companyName,
          email: me.email || current.email,
        };
        saveSession(next);
        setSession(next);
      } catch {
        if (!cancelled) {
          clearSession();
          setSession(null);
        }
      } finally {
        if (!cancelled) setReady(true);
      }
    }
    void validate();
    return () => {
      cancelled = true;
    };
  }, []);

  const login = useCallback(async (email: string, password: string) => {
    const data = await api<{
      access_token: string;
      tenant_id: string;
      company_name: string;
      email: string;
    }>("/api/v1/auth/login", {
      method: "POST",
      body: JSON.stringify({ email, password }),
    });
    const next: Session = {
      token: data.access_token,
      tenantId: data.tenant_id,
      companyName: data.company_name,
      email: data.email,
    };
    saveSession(next);
    setSession(next);
  }, []);

  const signup = useCallback(
    async (companyName: string, email: string, password: string) => {
      const data = await api<{
        access_token: string;
        tenant_id: string;
        company_name: string;
        email: string;
      }>("/api/v1/auth/signup", {
        method: "POST",
        body: JSON.stringify({
          company_name: companyName,
          email,
          password,
        }),
      });
      const next: Session = {
        token: data.access_token,
        tenantId: data.tenant_id,
        companyName: data.company_name,
        email: data.email,
      };
      saveSession(next);
      setSession(next);
    },
    []
  );

  const value = useMemo(
    () => ({ session, ready, login, signup, logout }),
    [session, ready, login, signup, logout]
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth() {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth outside AuthProvider");
  return ctx;
}
