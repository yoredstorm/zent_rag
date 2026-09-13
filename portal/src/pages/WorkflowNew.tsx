import { FlowArrow, MagicWand, PencilSimple, SquaresFour } from "@phosphor-icons/react";
import { useCallback, useEffect, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { api } from "../api";
import { useAuth } from "../auth";
import { Breadcrumb } from "../components/Breadcrumb";
import { ErrorInline, PageHeader, SkeletonBlock } from "../components/ui";
import type { WorkflowTemplate } from "../components/workflowStudio/types";

export default function WorkflowNewPage() {
  const { session } = useAuth();
  const navigate = useNavigate();
  const [templates, setTemplates] = useState<WorkflowTemplate[]>([]);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState("");
  const [error, setError] = useState("");

  const load = useCallback(async () => {
    if (!session) return;
    try {
      const data = await api<{ templates: WorkflowTemplate[] }>("/api/v1/workflows/templates", {
        token: session.token,
        organizationId: session.organizationId,
      });
      setTemplates(data.templates || []);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Error");
    } finally {
      setLoading(false);
    }
  }, [session]);

  useEffect(() => {
    void load();
  }, [load]);

  async function install(slug: string) {
    if (!session) return;
    setBusy(slug);
    setError("");
    try {
      const out = await api<{ workflow_id: string; hook_secret?: string }>(
        `/api/v1/workflows/templates/${slug}/install`,
        { method: "POST", token: session.token, organizationId: session.organizationId },
      );
      navigate(`/workflows/${out.workflow_id}`, { state: { hookSecret: out.hook_secret } });
    } catch (e) {
      setError(e instanceof Error ? e.message : "Error");
      setBusy("");
    }
  }

  return (
    <div className="space-y-5">
      <Breadcrumb items={[{ label: "Workflows", to: "/workflows" }, { label: "Nuevo workflow" }]} />
      <PageHeader
        title="¿Cómo quieres crear tu automatización?"
        subtitle="La opción recomendada es contar qué necesitas; el lienzo avanzado sigue disponible."
      />
      <ErrorInline message={error} />

      <div className="grid gap-4 lg:grid-cols-3">
        <Link
          to="/workflows/new/ask"
          className="panel group relative flex flex-col gap-2 border-accent/40 p-5 hover:border-accent"
          data-testid="wf-mode-ai"
        >
          <span className="badge badge-info absolute top-3 right-3">Recomendado</span>
          <MagicWand size={22} className="text-accent" aria-hidden />
          <h2 className="text-base font-semibold text-text">Crear con IA</h2>
          <p className="text-xs text-muted">
            Describe qué quieres automatizar. Zent lo explica en lenguaje de negocio y tú confirmas
            antes de crear nada.
          </p>
          <span className="mt-auto text-[11px] font-medium text-accent group-hover:underline">
            Empezar a describir →
          </span>
        </Link>

        <Link
          to="/workflows/new/manual"
          className="panel group flex flex-col gap-2 p-5 hover:border-accent/50"
          data-testid="wf-mode-manual"
        >
          <PencilSimple size={22} className="text-muted" aria-hidden />
          <h2 className="text-base font-semibold text-text">Diseñar manualmente</h2>
          <p className="text-xs text-muted">
            Lienzo avanzado: nodos, puertos, condiciones, reintentos y control total del grafo.
          </p>
          <span className="mt-auto text-[11px] font-medium text-accent group-hover:underline">
            Abrir el lienzo →
          </span>
        </Link>

        <section className="panel flex flex-col gap-2 p-5" data-testid="wf-mode-templates">
          <SquaresFour size={22} className="text-info" aria-hidden />
          <h2 className="text-base font-semibold text-text">Usar una plantilla</h2>
          <p className="text-xs text-muted">Recetas listas para configurar y adaptar.</p>
          {loading ? (
            <SkeletonBlock rows={3} />
          ) : templates.length === 0 ? (
            <p className="text-[11px] text-faint">Sin plantillas disponibles todavía.</p>
          ) : (
            <ul className="mt-1 space-y-1">
              {templates.slice(0, 5).map((template) => (
                <li key={template.slug} className="flex items-center gap-2 rounded-md bg-soft px-2 py-1.5">
                  <FlowArrow size={12} className="shrink-0 text-info" aria-hidden />
                  <span className="min-w-0 flex-1 truncate text-[11px] text-text">{template.name}</span>
                  <button
                    type="button"
                    className="btn btn-ghost min-h-7 px-1.5 text-[10px]"
                    disabled={!!busy}
                    data-testid={`wf-new-install-${template.slug}`}
                    onClick={() => void install(template.slug)}
                  >
                    {busy === template.slug ? "…" : "Usar"}
                  </button>
                </li>
              ))}
            </ul>
          )}
        </section>
      </div>
    </div>
  );
}
