import { CheckCircle, XCircle } from "@phosphor-icons/react";
import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { saveSession } from "../api";
import { Button } from "../components/ui/Button";
import { Spinner } from "../components/ui/states";

export default function SsoCallbackPage() {
  const navigate = useNavigate();
  const [error, setError] = useState("");

  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    const token = params.get("token");
    const org = params.get("org");
    if (!token || !org) {
      setError("El proveedor no devolvió una sesión válida. Probá iniciar sesión de nuevo.");
      return;
    }
    try {
      // Guarda la sesión con el esquema real del portal (FASE 17: callback SSO corregido).
      saveSession({ token, organizationId: org, companyName: "", email: undefined });
      navigate("/", { replace: true });
    } catch {
      setError("No pudimos guardar la sesión en este navegador.");
    }
  }, [navigate]);

  return (
    <div className="flex min-h-[100dvh] items-center justify-center px-4 py-10">
      <div className="flex w-full max-w-[380px] flex-col items-center gap-4 text-center">
        {error ? (
          <>
            <span className="flex h-11 w-11 items-center justify-center rounded-md border border-danger/25 bg-danger-soft text-danger">
              <XCircle size={22} aria-hidden />
            </span>
            <div>
              <p className="text-h3">No pudimos completar el SSO</p>
              <p className="mt-1 text-[13px] leading-relaxed text-muted">{error}</p>
            </div>
            <Button variant="secondary" onClick={() => navigate("/login")}>
              Ir al login
            </Button>
          </>
        ) : (
          <>
            <span className="flex h-11 w-11 items-center justify-center rounded-md border border-accent-line bg-accent-soft text-accent">
              <CheckCircle size={22} aria-hidden />
            </span>
            <p className="flex items-center gap-2 text-sm text-muted" role="status" aria-live="polite">
              <Spinner size={14} />
              Sesión verificada por SSO. Entrando a tu workspace…
            </p>
          </>
        )}
      </div>
    </div>
  );
}
