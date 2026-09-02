import { CheckCircle, XCircle } from "@phosphor-icons/react";
import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { Spinner } from "../components/ui";

export default function SsoCallbackPage() {
  const navigate = useNavigate();
  const [error, setError] = useState("");

  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    const token = params.get("token");
    const org = params.get("org");
    if (!token) {
      setError("Faltó el token de sesión en el callback SSO.");
      return;
    }
    try {
      localStorage.setItem("rag_session", token);
      if (org) localStorage.setItem("rag_org", org);
      navigate("/", { replace: true });
    } catch {
      setError("No se pudo guardar la sesión.");
    }
  }, [navigate]);

  if (error) {
    return (
      <div className="flex min-h-screen flex-col items-center justify-center gap-3 bg-soft p-6 text-center">
        <XCircle size={40} className="text-danger" aria-hidden />
        <p className="text-sm text-text">{error}</p>
        <button type="button" className="btn btn-secondary min-h-11" onClick={() => navigate("/login")}>
          Ir al login
        </button>
      </div>
    );
  }
  return (
    <div className="flex min-h-screen flex-col items-center justify-center gap-3 bg-soft p-6 text-center">
      <CheckCircle size={40} className="text-success" aria-hidden />
      <p className="flex items-center gap-2 text-sm text-text">
        <Spinner size={14} /> Sesión iniciada vía SSO, redirigiendo…
      </p>
    </div>
  );
}