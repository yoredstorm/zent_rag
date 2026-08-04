import {
  createContext,
  useCallback,
  useContext,
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
  loginWithToken: (token: string, tenantId: string, companyName?: string) => void;
  signup: (companyName: string, email?: string) => Promise<void>;
  logout: () => void;
  updateToken: (token: string) => void;
};

const AuthContext = createContext<AuthContextValue | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [session, setSession] = useState<Session | null>(() => loadSession());

  const loginWithToken = useCallback(
    (token: string, tenantId: string, companyName = "") => {
      const next = { token, tenantId, companyName };
      saveSession(next);
      setSession(next);
    },
    []
  );

  const signup = useCallback(async (companyName: string, email?: string) => {
    const data = await api<{
      api_token: string;
      tenant_id: string;
      company_name: string;
    }>("/api/v1/billing/subscription/create-trial", {
      method: "POST",
      body: JSON.stringify({ company_name: companyName, email }),
    });
    loginWithToken(data.api_token, data.tenant_id, data.company_name);
  }, [loginWithToken]);

  const logout = useCallback(() => {
    clearSession();
    setSession(null);
  }, []);

  const updateToken = useCallback(
    (token: string) => {
      setSession((prev) => {
        if (!prev) return prev;
        const next = { ...prev, token };
        saveSession(next);
        return next;
      });
    },
    []
  );

  const value = useMemo(
    () => ({ session, loginWithToken, signup, logout, updateToken }),
    [session, loginWithToken, signup, logout, updateToken]
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth() {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth outside AuthProvider");
  return ctx;
}
