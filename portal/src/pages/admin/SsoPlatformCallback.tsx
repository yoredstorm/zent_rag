import { CheckCircle, XCircle } from "@phosphor-icons/react";
import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { Button } from "../../components/ui/Button";
import { Spinner } from "../../components/ui/states";
import { persistPlatformSession } from "../../platformAuth";

/**
 * Retorno del login con Zitadel.
 *
 * El API valida el id_token y emite su propia sesión de plataforma; acá solo se
 * guarda y se entra al Control Center. Vive fuera de `/control-center` para que
 * el guard del layout no redirija antes de guardar.
 */
export default function SsoPlatformCallback() {
  const navigate = useNavigate();
  const [error, setError] = useState("");
  const [email, setEmail] = useState("");

  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    const token = params.get("token");
    const returnedEmail = params.get("email") ?? "";
    const message = params.get("error");

    if (message || !token) {
      setError(message || "Zitadel no devolvió una sesión válida.");
      setEmail(returnedEmail);
      return;
    }
    persistPlatformSession({ token, email: returnedEmail });
    navigate("/control-center", { replace: true });
  }, [navigate]);

  return (
    <div className="flex min-h-[100dvh] items-center justify-center px-4 py-10">
      <div className="flex w-full max-w-[420px] flex-col items-center gap-4 text-center">
        {error ? (
          <>
            <span className="flex h-11 w-11 items-center justify-center rounded-md border border-danger/25 bg-danger-soft text-danger">
              <XCircle size={22} aria-hidden />
            </span>
            <div>
              <p className="text-h3">No pudimos completar el login</p>
              <p className="mt-1 text-[13px] leading-relaxed text-muted">{error}</p>
              {email && (
                <p className="mt-2 font-mono text-xs text-faint">{email}</p>
              )}
            </div>
            <Button variant="secondary" onClick={() => navigate("/control-center/login")}>
              Volver al login
            </Button>
          </>
        ) : (
          <>
            <span className="flex h-11 w-11 items-center justify-center rounded-md border border-ok/25 bg-ok-soft text-ok">
              <CheckCircle size={22} aria-hidden />
            </span>
            <p className="text-h3">Sesión iniciada</p>
            <Spinner />
          </>
        )}
      </div>
    </div>
  );
}
