import { Code, FlowArrow, MagicWand, PencilSimple, Play, Plus, SquaresFour, Trash } from "@phosphor-icons/react";
import { useCallback, useEffect, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { api } from "../api";
import { useAuth } from "../auth";
import { EmptyState, ErrorInline, PageHeader, SkeletonBlock, SuccessInline } from "../components/ui";
import {
  STATUS_BADGE,
  type WorkflowSummary,
  type WorkflowTemplate,
} from "../components/workflowStudio/types";

export default function WorkflowsPage() {
  const { session } = useAuth();
  const navigate = useNavigate();
  const [wfs, setWfs] = useState<WorkflowSummary[]>([]);
  const [tpls, setTpls] = useState<WorkflowTemplate[]>([]);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState("");
  const [error, setError] = useState("");
  const [msg, setMsg] = useState("");

  const load = useCallback(async () => {
    if (!session) return;
    setError("");
    try {
      const [w, t] = await Promise.all([
        api<{ workflows: WorkflowSummary[] }>("/api/v1/workflows", {
          token: session.token,
          organizationId: session.organizationId,
        }),
        api<{ templates: WorkflowTemplate[] }>("/api/v1/workflows/templates", {
          token: session.token,
          organizationId: session.organizationId,
        }),
      ]);
      setWfs(w.workflows || []);
      setTpls(t.templates || []);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Error");
    } finally {
      setLoading(false);
    }
  }, [session]);

  useEffect(() => {
    void load();
  }, [load]);

  async function install(slug: string) {
    if (!session) return;
    setBusy(`i-${slug}`);
    setError("");
    setMsg("");
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

  async function toggle(wf: WorkflowSummary) {
    if (!session) return;
    const action = wf.status === "active" ? "pause" : "activate";
    setBusy(`${action}-${wf.id}`);
    setError("");
    setMsg("");
    try {
      await api(`/api/v1/workflows/${wf.id}/${action}`, {
        method: "POST",
        token: session.token,
        organizationId: session.organizationId,
      });
      setMsg(action === "activate" ? `"${wf.name}" está activo.` : `"${wf.name}" pausado.`);
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Error");
    } finally {
      setBusy("");
    }
  }

  async function remove(wf: WorkflowSummary) {
    if (!session) return;
    if (!window.confirm(`¿Eliminar el workflow "${wf.name}"? Sus runs dejarán de ser accesibles.`)) {
      return;
    }
    setBusy(`del-${wf.id}`);
    setError("");
    setMsg("");
    try {
      await api(`/api/v1/workflows/${wf.id}`, {
        method: "DELETE",
        token: session.token,
        organizationId: session.organizationId,
      });
      setMsg(`Workflow "${wf.name}" eliminado.`);
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Error");
    } finally {
      setBusy("");
    }
  }

  return (
    <div>
      <PageHeader
        title="Workflow Automation"
        subtitle="Dile a Zent qué quieres automatizar o diseña el grafo tú mismo."
        actions={
          <div className="flex flex-wrap gap-2">
            <Link to="/workflows/new" className="btn btn-secondary min-h-11" data-testid="wf-new-modes">
              <Plus size={15} aria-hidden />
              Nuevo workflow
            </Link>
            <Link to="/workflows/new/ask" className="btn btn-primary min-h-11" data-testid="wf-new-ai">
              <MagicWand size={15} aria-hidden />
              Crear con IA
            </Link>
          </div>
        }
      />
      <ErrorInline message={error} />
      <SuccessInline message={msg} />

      {loading ? (
        <div className="panel p-5">
          <SkeletonBlock rows={4} />
        </div>
      ) : wfs.length === 0 ? (
        <div className="panel">
          <EmptyState
            icon={FlowArrow}
            title="Sin workflows"
            body="Cuéntale a Zent qué quieres automatizar, instala una plantilla o diseña el lienzo tú mismo."
            action={
              <Link to="/workflows/new/ask" className="btn btn-primary min-h-11">
                <MagicWand size={15} aria-hidden />
                Crear con IA
              </Link>
            }
          />
        </div>
      ) : (
        <section>
          <h2 className="mb-2 text-sm font-semibold text-text">Workflows ({wfs.length})</h2>
          <div className="grid gap-4 sm:grid-cols-2">
            {wfs.map((w) => (
              <div
                key={w.id}
                className="panel cursor-pointer p-5"
                data-testid="wf-card"
                onClick={(event) => {
                  if ((event.target as HTMLElement).closest("a, button")) return;
                  navigate(`/workflows/${w.id}`);
                }}
              >
                <div className="mb-2 flex items-start justify-between gap-2">
                  <Link
                    to={`/workflows/${w.id}`}
                    className="flex items-center gap-2 font-semibold text-text hover:text-accent"
                  >
                    <FlowArrow size={16} className="text-accent" aria-hidden />
                    {w.name}
                  </Link>
                  <button
                    type="button"
                    className="btn btn-ghost min-h-11 px-2 py-1.5 text-xs text-danger"
                    aria-label={`Eliminar ${w.name}`}
                    disabled={!!busy}
                    onClick={() => void remove(w)}
                  >
                    <Trash size={14} aria-hidden />
                  </button>
                </div>
                <p className="mb-3 text-sm text-muted">{w.description || "Sin descripción aún"}</p>
                <div className="mb-3 flex flex-wrap items-center gap-2 text-xs text-faint">
                  <span className={`badge ${STATUS_BADGE[w.status] ?? "badge-muted"}`}>{w.status}</span>
                  <span className="badge badge-muted">{w.trigger_type}</span>
                  <span>
                    {w.ok_runs}/{w.runs} ok
                  </span>
                </div>
                <div className="flex flex-wrap gap-2">
                  <Link to={`/workflows/${w.id}`} className="btn btn-secondary min-h-11">
                    <PencilSimple size={14} aria-hidden />
                    Editar
                  </Link>
                  <Link to={`/workflows/${w.id}?panel=test`} className="btn btn-secondary min-h-11">
                    <Play size={14} aria-hidden />
                    Probar
                  </Link>
                  <Link to={`/workflows/${w.id}?panel=api`} className="btn btn-secondary min-h-11">
                    <Code size={14} aria-hidden />
                    API
                  </Link>
                  <button
                    type="button"
                    className="btn btn-ghost min-h-11"
                    disabled={!!busy}
                    onClick={() => void toggle(w)}
                    data-testid={`wf-toggle-${w.id}`}
                  >
                    {w.status === "active" ? "Pausar" : "Activar"}
                  </button>
                </div>
              </div>
            ))}
          </div>
        </section>
      )}

      {!loading && (
        <section className="panel mt-6 space-y-2 p-4">
          <h3 className="text-sm font-semibold text-text">Plantillas</h3>
          <p className="text-xs text-muted">Instalar abre el estudio con el flujo ya armado.</p>
          <div className="grid grid-cols-1 gap-2 sm:grid-cols-2 lg:grid-cols-3">
            {tpls.map((t) => (
              <div key={t.slug} className="flex items-center gap-2 rounded-md bg-soft px-3 py-2 text-xs">
                <SquaresFour size={12} className="text-faint" aria-hidden />
                <span className="flex-1 text-text">{t.name}</span>
                <span className="text-[10px] text-faint">{t.steps.length} pasos</span>
                <button
                  type="button"
                  data-testid={`wf-install-${t.slug}`}
                  className="btn btn-ghost min-h-8 px-2 text-[10px]"
                  disabled={!!busy}
                  onClick={() => void install(t.slug)}
                >
                  Instalar
                </button>
              </div>
            ))}
            {tpls.length === 0 && <p className="text-xs text-faint">Sin plantillas disponibles.</p>}
          </div>
        </section>
      )}

      <p className="mt-6 text-[11px] text-faint">
        La URL del hook inbound, el secret, los snippets y el contrato Android viven en el drawer
        API de cada workflow.
      </p>
    </div>
  );
}
