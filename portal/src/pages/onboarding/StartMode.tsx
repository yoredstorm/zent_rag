import { Books, PencilSimple } from "@phosphor-icons/react";
import { useState } from "react";
import { Navigate, useNavigate } from "react-router-dom";
import { api } from "../../api";
import { useAuth } from "../../auth";
import { Brand } from "../../components/Brand";
import { ErrorInline } from "../../components/ui/states";
import { cn } from "../../components/ui/cn";

type Choice = "demo" | "blank";

const OPTIONS: {
  id: Choice;
  testId: string;
  icon: typeof Books;
  title: string;
  body: string;
  next: string;
}[] = [
  {
    id: "demo",
    testId: "start-mode-demo",
    icon: Books,
    title: "Explorar con datos de ejemplo",
    body: "Cargamos un catálogo de prueba: podés preguntar en el Playground desde el primer minuto.",
    next: "Después vas a poder conectar tus propias fuentes o migrar lo que ya probaste.",
  },
  {
    id: "blank",
    testId: "start-mode-blank",
    icon: PencilSimple,
    title: "Empezar de cero",
    body: "Workspace vacío, sin fuentes ni conexiones.",
    next: "El siguiente paso es conectar tus datos para que Zent aprenda tu negocio.",
  },
];

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
      setError(
        err instanceof Error
          ? err.message
          : "No pudimos preparar el workspace. Revisá la conexión e intentá de nuevo."
      );
    } finally {
      setBusy(null);
    }
  }

  return (
    <div className="flex min-h-[100dvh] flex-col px-5 py-8 sm:px-8">
      <div className="mx-auto flex w-full max-w-3xl flex-1 flex-col justify-center">
        <Brand />
        <p className="eyebrow mt-8 mb-2">Cómo empezar</p>
        <h1 className="text-display">Prepará tu workspace</h1>
        <p className="prose-measure mt-2.5 text-sm leading-relaxed text-muted">
          El trial es el mismo en ambos casos. Elegí si querés ver Zent funcionando con datos de
          prueba o arrancar con un espacio vacío.
        </p>

        <ErrorInline message={error} className="mt-6" />

        <div className="mt-7 grid gap-3 md:grid-cols-2">
          {OPTIONS.map((option) => (
            <button
              key={option.id}
              type="button"
              data-testid={option.testId}
              disabled={busy !== null}
              aria-busy={busy === option.id}
              onClick={() => void choose(option.id)}
              className={cn(
                "panel group flex flex-col items-start gap-3 p-5 text-left",
                "transition-[border-color,background-color,transform] duration-200 ease-[var(--ease-out)]",
                "hover:-translate-y-px hover:border-border-strong hover:bg-raised",
                busy !== null && "cursor-not-allowed opacity-60"
              )}
            >
              <span className="flex h-10 w-10 items-center justify-center rounded-md border border-border bg-raised text-accent transition-colors duration-200 group-hover:border-accent-line group-hover:bg-accent-soft">
                <option.icon size={19} aria-hidden />
              </span>
              <span className="text-[15px] font-semibold text-text">{option.title}</span>
              <span className="text-[13px] leading-relaxed text-muted">{option.body}</span>
              <span className="mt-auto pt-2 text-[11px] leading-relaxed text-faint">
                {busy === option.id ? "Preparando…" : option.next}
              </span>
            </button>
          ))}
        </div>

        <p className="mt-6 text-xs text-faint">
          Podés cambiar de workspace después, sin perder esta decisión.
        </p>
      </div>
    </div>
  );
}
