import { createContext, useContext, useEffect, useMemo, useState, type ReactNode } from "react";
import { api } from "../api";
import { useAuth } from "../auth";

export type Entitlements = Record<string, boolean | number | null>;

const EntitlementsContext = createContext<Entitlements>({});

/**
 * Entitlements del tenant, resueltos una sola vez por sesión.
 * Sidebar, paleta de comandos y páginas leen de acá en vez de repetir el fetch.
 */
export function EntitlementsProvider({ children }: { children: ReactNode }) {
  const { session } = useAuth();
  const [entitlements, setEntitlements] = useState<Entitlements>({});

  useEffect(() => {
    if (!session) {
      setEntitlements({});
      return;
    }
    let cancelled = false;
    api<{ entitlements: Entitlements }>("/api/v1/billing/entitlements", {
      token: session.token,
      organizationId: session.organizationId,
    })
      .then((out) => {
        if (!cancelled) setEntitlements(out.entitlements || {});
      })
      .catch(() => {
        if (!cancelled) setEntitlements({});
      });
    return () => {
      cancelled = true;
    };
  }, [session]);

  const value = useMemo(() => entitlements, [entitlements]);
  return <EntitlementsContext.Provider value={value}>{children}</EntitlementsContext.Provider>;
}

export function useEntitlements(): Entitlements {
  return useContext(EntitlementsContext);
}
