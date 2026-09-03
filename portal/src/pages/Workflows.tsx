import { FlowArrow, Lightning, Play, SquaresFour } from "@phosphor-icons/react";
import { useEffect, useState } from "react";
import { api } from "../api";
import { useAuth } from "../auth";
import { ErrorInline, PageHeader, SkeletonBlock } from "../components/ui";

type WF = { id: string; name: string; description: string | null; trigger_type: string; status: string; runs: number; ok_runs: number; created_at: string };
type Tpl = { slug: string; name: string; description: string; category: string; trigger_type: string; steps: { type: string }[] };
type Run = { id: string; workflow_id: string; workflow_name: string; status: string; started_at: string; duration_ms: number | null; error: string | null };
type StepRow = { step_index: number; step_type: string; status: string; output: Record<string, unknown>; error: string | null; retries: number; duration_ms: number | null };

const ST: Record<string, string> = { succeeded: "badge-ok", failed: "badge-danger", running: "badge-warning", paused: "badge-warning", draft: "badge-muted", active: "badge-ok" };

export default function WorkflowsPage() {
  const { session } = useAuth();
  const [wfs, setWfs] = useState<WF[]>([]);
  const [tpls, setTpls] = useState<Tpl[]>([]);
  const [selected, setSelected] = useState<string | null>(null);
  const [runs, setRuns] = useState<Run[]>([]);
  const [steps, setSteps] = useState<StepRow[] | null>(null);
  const [draft, setDraft] = useState({ name: "", trigger_type: "webhook", steps: "" });
  const [payload, setPayload] = useState("{}");
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState("");
  const [error, setError] = useState("");

  async function load() {
    if (!session) return;
    setError("");
    try {
      const [w, t] = await Promise.all([
        api<{ workflows: WF[] }>("/api/v1/workflows", { token: session.token, organizationId: session.organizationId }),
        api<{ templates: Tpl[] }>("/api/v1/workflows/templates", { token: session.token, organizationId: session.organizationId }),
      ]);
      setWfs(w.workflows || []);
      setTpls(t.templates || []);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Error");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    void load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [session]);

  async function create() {
    if (!session || !draft.name) return;
    setBusy("create");
    setError("");
    try {
      let steps: { type: string }[] = [];
      try {
        const parsed = JSON.parse(draft.steps || "[]");
        steps = Array.isArray(parsed) ? parsed : [];
      } catch {
        setError("steps no es JSON válido");
        setBusy("");
        return;
      }
      const out = await api<{ workflow_id: string }>("/api/v1/workflows", {
        method: "POST",
        token: session.token,
        organizationId: session.organizationId,
        body: JSON.stringify({ name: draft.name, trigger_type: draft.trigger_type, steps }),
      });
      setError(`Workflow creado: ${out.workflow_id.slice(0, 8)}…`);
      setDraft({ name: "", trigger_type: "webhook", steps: "" });
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Error");
    } finally {
      setBusy("");
    }
  }

  async function install(slug: string) {
    if (!session) return;
    setBusy(`i-${slug}`);
    await api(`/api/v1/workflows/templates/${slug}/install`, { method: "POST", token: session.token, organizationId: session.organizationId });
    setBusy("");
    await load();
  }

  async function select(id: string) {
    setSelected(id);
    setSteps(null);
    if (!session) return;
    const r = await api<{ runs: Run[] }>(`/api/v1/workflows/${id}/runs`, { token: session.token, organizationId: session.organizationId });
    setRuns(r.runs || []);
  }

  async function act(id: string, action: "run" | "activate" | "pause") {
    if (!session) return;
    setBusy(`${action}-${id.slice(0, 6)}`);
    setError("");
    try {
      const body = action === "run" ? JSON.stringify({ payload: JSON.parse(payload || "{}") }) : undefined;
      const out = await api<Record<string, unknown>>(`/api/v1/workflows/${id}/${action}`, {
        method: "POST",
        token: session.token,
        organizationId: session.organizationId,
        body,
      });
      setError(`${action}: ${JSON.stringify(out).slice(0, 100)}`);
      if (action === "run" && selected === id) await select(id);
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Error");
    } finally {
      setBusy("");
    }
  }

  async function showRun(runId: string) {
    if (!session) return;
    const d = await api<{ steps: StepRow[] }>(`/api/v1/workflows/runs/${runId}`, { token: session.token, organizationId: session.organizationId });
    setSteps(d.steps || []);
  }

  return (
    <div className="space-y-6">
      <PageHeader title="Workflow Automation" subtitle="Editor de workflows multi-paso con disparadores, retries y ejecución trazable." />
      {error && <ErrorInline>{error}</ErrorInline>}
      {loading ? (
        <SkeletonBlock className="h-64" />
      ) : (
        <div className="grid grid-cols-1 gap-6 lg:grid-cols-3">
          <section className="panel p-4">
            <h2 className="mb-2 flex items-center gap-2 text-sm font-semibold text-text"><Lightning size={14} /> Nuevo workflow</h2>
            <div className="grid grid-cols-1 gap-2">
              <input className="rounded-md border border-border bg-soft px-2 py-2 text-sm" placeholder="nombre…" value={draft.name} onChange={(e) => setDraft((d) => ({ ...d, name: e.target.value }))} />
              <select className="rounded-md border border-border bg-soft px-2 py-2 text-sm" value={draft.trigger_type} onChange={(e) => setDraft((d) => ({ ...d, trigger_type: e.target.value }))}>
                {["webhook", "schedule", "event"].map((t) => (<option key={t} value={t}>{t}</option>))}
              </select>
              <textarea className="h-36 rounded-md border border-border bg-soft px-2 py-2 font-mono text-[11px]" placeholder='[{"type": "llm", "config": {"prompt": "hola"}}]' value={draft.steps} onChange={(e) => setDraft((d) => ({ ...d, steps: e.target.value }))} />
              <button type="button" className="btn btn-primary min-h-9 text-xs" disabled={!!busy || !draft.name} onClick={() => void create()}>Crear</button>
            </div>
            <h3 className="mb-2 mt-4 text-sm font-semibold text-text">Plantillas</h3>
            <div className="space-y-1">
              {tpls.map((t) => (
                <div key={t.slug} className="flex items-center gap-2 rounded-md bg-soft px-3 py-2 text-xs">
                  <SquaresFour size={12} className="text-faint" />
                  <span className="flex-1 text-text">{t.name}</span>
                  <span className="text-[10px] text-faint">{t.steps.length} pasos</span>
                  <button type="button" className="btn btn-ghost min-h-6 px-2 text-[10px]" disabled={!!busy} onClick={() => void install(t.slug)}>Instalar</button>
                </div>
              ))}
            </div>
          </section>

          <section className="lg:col-span-2">
            <h2 className="mb-2 text-sm font-semibold text-text">Workflows ({wfs.length})</h2>
            <div className="panel space-y-2 p-3">
              {wfs.map((w) => (
                <div key={w.id} className={`rounded-md border p-3 ${selected === w.id ? "border-accent bg-accent/5" : "border-border bg-soft/50"}`}>
                  <div className="flex items-center gap-2">
                    <FlowArrow size={14} className="text-accent" />
                    <button type="button" className="text-sm font-medium text-text" onClick={() => void select(w.id)}>{w.name}</button>
                    <span className={`badge ${ST[w.status] ?? "badge-muted"}`}>{w.status}</span>
                    <span className="badge badge-muted">{w.trigger_type}</span>
                    <span className="flex-1" />
                    <span className="text-[10px] text-faint">{w.ok_runs}/{w.runs} ok</span>
                    <button type="button" className="btn btn-ghost min-h-7 px-2 text-[11px]" disabled={!!busy} onClick={() => void act(w.id, "run")}><Play size={11} /> Ejecutar</button>
                    {w.status !== "active" ? (
                      <button type="button" className="btn btn-ghost min-h-7 px-2 text-[11px]" disabled={!!busy} onClick={() => void act(w.id, "activate")}>Activar</button>
                    ) : (
                      <button type="button" className="btn btn-ghost min-h-7 px-2 text-[11px]" disabled={!!busy} onClick={() => void act(w.id, "pause")}>Pausar</button>
                    )}
                  </div>
                  <div className="mt-1 flex gap-2">
                    <input className="flex-1 rounded-md border border-border bg-soft px-2 py-1 font-mono text-[10px]" placeholder='{"message": "hola"}' value={payload} onChange={(e) => setPayload(e.target.value)} />
                  </div>
                </div>
              ))}
              {wfs.length === 0 && <p className="text-xs text-faint">Sin workflows. Crea uno o instala una plantilla.</p>}
            </div>

            {selected && (
              <div className="panel mt-2 p-3">
                <h3 className="mb-2 text-sm font-semibold text-text">Runs recientes</h3>
                <div className="space-y-1">
                  {runs.map((r) => (
                    <div key={r.id} className="flex items-center gap-2 rounded-md bg-soft px-3 py-1.5 text-[11px]">
                      <span className={`badge ${ST[r.status] ?? "badge-muted"}`}>{r.status}</span>
                      <span className="flex-1 text-text">{r.id.slice(0, 8)}… · {new Date(r.started_at).toLocaleTimeString()}</span>
                      <span className="text-faint">{r.duration_ms != null ? `${r.duration_ms}ms` : "—"}</span>
                      <button type="button" className="btn btn-ghost min-h-6 px-2 text-[10px]" onClick={() => void showRun(r.id)}>pasos</button>
                    </div>
                  ))}
                  {runs.length === 0 && <p className="text-xs text-faint">Sin runs.</p>}
                </div>
                {steps && (
                  <div className="mt-2 rounded-md border border-border p-2">
                    <h4 className="mb-1 text-xs font-semibold text-text">Pasos del run</h4>
                    {steps.map((s) => (
                      <div key={s.step_index} className="flex items-start gap-2 rounded bg-soft px-2 py-1 text-[11px]">
                        <span className={`badge ${ST[s.status] ?? "badge-muted"}`}>{s.status}</span>
                        <span className="font-medium text-text">#{s.step_index} {s.step_type}</span>
                        <span className="text-faint">retries {s.retries} · {s.duration_ms ?? "—"}ms</span>
                        {s.error && <span className="text-red-400">{s.error}</span>}
                      </div>
                    ))}
                  </div>
                )}
              </div>
            )}
          </section>
        </div>
      )}
    </div>
  );
}