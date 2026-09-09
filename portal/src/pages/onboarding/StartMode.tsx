import { Books, PencilSimple } from "@phosphor-icons/react";
import { useState } from "react";
import { Navigate, useNavigate } from "react-router-dom";
import { api } from "../../api";
import { useAuth } from "../../auth";
import { Spinner } from "../../components/ui";

type Choice = "demo" | "blank";

export default function StartModePage() {
  const { session, ready, applySession } = useAuth();
  const navigate = useNavigate();
  const [busy, setBusy] = useState<Choice | null>(null);
  const [error, setError] = useState("");

  if (!ready) {
    return (
      <div className="flex min-h-[100dvh] items-center justify-center text-muted">
        Cargando sesión…
      </div>
    );
  }
  if (!session) return <Navigate to="/login" replace />;
  if (!session.needsStartMode) return <Navigate to="/" replace />;

  async function choose(mode: Choice) {
    if (!session) return;
    setBusy(mode);
    setError("");
    try {
      const data = await api<{
        workspace_id: string;
        kind: string;
        needs_start_mode?: boolean;
      }>("/api/v1/onboarding/start-mode", {
        method: "POST",
        token: session.token,
        organizationId: session.organizationId,
        body: JSON.stringify({ mode }),
      });
      applySession({
        ...session,
        workspaceId: data.workspace_id,
        workspaceKind: data.kind,
        needsStartMode: false,
      });
      navigate("/", { replace: true });
    } catch (err) {
      setError(err instanceof Error ? err.message : "Error al empezar");
    } finally {
      setBusy(null);
    }
  }

  return (
    <div className="flex min-h-[100dvh] items-center justify-center px-4 py-10">
      <div className="w-full max-w-2xl">
        <div className="mb-8 text-center">
          <h1 className="text-2xl font-semibold tracking-tight text-text">
            ¿Cómo quieres empezar?
          </h1>
          <p className="mt-2 text-sm text-muted">
            El trial queda igual. Eliges si exploras con datos de prueba o un espacio vacío.
          </p>
        </div>
        <div className="grid gap-4 md:grid-cols-2">
          <button
            type="button"
            data-testid="start-mode-demo"
            className="panel flex flex-col items-start gap-3 p-6 text-left transition hover:border-accent/40"
            disabled={busy !== null}
            onClick={() => void choose("demo")}
          >
            <Books size={28} className="text-accent" aria-hidden />
            <span className="text-base font-semibold text-text">
              Probar con datos de ejemplo
            </span>
            <span className="text-sm text-muted">
              Catálogo de prueba listo. El chat responde desde el primer minuto.
            </span>
            {busy === "demo" && <Spinner size={16} />}
          </button>
          <button
            type="button"
            data-testid="start-mode-blank"
            className="panel flex flex-col items-start gap-3 p-6 text-left transition hover:border-accent/40"
            disabled={busy !== null}
            onClick={() => void choose("blank")}
          >
            <PencilSimple size={28} className="text-accent" aria-hidden />
            <span className="text-base font-semibold text-text">Empezar de cero</span>
            <span className="text-sm text-muted">
              Sin fuentes ni conexiones. Conecta tus datos cuando quieras.
            </span>
            {busy === "blank" && <Spinner size={16} />}
          </button>
        </div>
        {error && (
          <p className="mt-4 text-center text-sm text-danger" role="alert">
            {error}
          </p>
        )}
      </div>
    </div>
  );
}

