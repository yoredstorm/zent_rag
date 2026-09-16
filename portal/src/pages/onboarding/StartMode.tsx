import { useEffect, useRef, useState } from "react";
import { Navigate, useNavigate } from "react-router-dom";
import { api } from "../../api";
import { useAuth } from "../../auth";
import { Brand } from "../../components/Brand";
import { ErrorInline, Spinner } from "../../components/ui";

/**
 * Preparación del espacio de trabajo.
 *
 * Ya no hay elección ("de prueba" vs "de cero"): cada organización arranca con
 * un workspace vacío, así que este paso se resuelve solo. La pantalla existe
 * únicamente como red de seguridad para sesiones que llegan sin workspace (por
 * ejemplo una organización creada antes de este cambio).
 */
export default function StartModePage() {
  const { session, ready, applySession } = useAuth();
  const navigate = useNavigate();
  const [error, setError] = useState("");
  const startedRef = useRef(false);

  useEffect(() => {
    if (!ready || !session?.needsStartMode || startedRef.current) return;
    startedRef.current = true;
    (async () => {
      try {
        const data = await api<{
          workspace_id: string;
          kind: string;
          needs_start_mode?: boolean;
        }>("/api/v1/onboarding/start-mode", {
          method: "POST",
          token: session.token,
          organizationId: session.organizationId,
          body: JSON.stringify({ mode: "blank" }),
        });
        applySession({
          ...session,
          workspaceId: data.workspace_id,
          workspaceKind: data.kind,
          needsStartMode: false,
        });
        navigate("/", { replace: true });
      } catch (err) {
        startedRef.current = false;
        setError(
          err instanceof Error
            ? err.message
            : "No pudimos preparar tu espacio. Reintentá en unos segundos."
        );
      }
    })();
  }, [ready, session, applySession, navigate]);

  if (!ready) {
    return (
      <div className="flex min-h-[100dvh] items-center justify-center text-muted">
        Cargando sesión…
      </div>
    );
  }
  if (!session) return <Navigate to="/login" replace />;
  if (!session.needsStartMode) return <Navigate to="/" replace />;

  return (
    <div className="flex min-h-[100dvh] flex-col items-center justify-center gap-4 px-6 text-center">
      <Brand />
      <p className="flex items-center gap-2.5 text-sm text-muted" role="status" aria-live="polite">
        <Spinner size={15} />
        Preparando tu espacio de trabajo…
      </p>
      <ErrorInline message={error} className="max-w-md" />
      {error && (
        <button
          type="button"
          className="btn btn-secondary btn-sm"
          onClick={() => window.location.reload()}
        >
          Reintentar
        </button>
      )}
    </div>
  );
}
