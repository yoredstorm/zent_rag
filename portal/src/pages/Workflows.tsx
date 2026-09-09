import { FlowArrow, Lightning, Play, SquaresFour } from "@phosphor-icons/react";
import { useEffect, useState } from "react";
import { api } from "../api";
import { useAuth } from "../auth";
import { WorkflowBlockEditor } from "../components/WorkflowBlockEditor";
import { ErrorInline, PageHeader, SkeletonBlock } from "../components/ui";
import { blocksToIr, irToBlocks, makeBlock, type BlockNode, type WorkflowStep } from "../lib/workflowIr";

type WF = {
  id: string;
  name: string;
  description: string | null;
  trigger_type: string;
  status: string;
  runs: number;
  ok_runs: number;
  created_at: string;
};
type Tpl = { slug: string; name: string; description: string; category: string; trigger_type: string; steps: { type: string }[] };
type Run = { id: string; workflow_id: string; workflow_name: string; status: string; started_at: string; duration_ms: number | null; error: string | null };
type StepRow = { step_index: number; step_type: string; status: string; output: Record<string, unknown>; error: string | null; retries: number; duration_ms: number | null };
type KB = { id: string; name: string };
type Agent = { id: string; name: string };

const ST: Record<string, string> = {
  succeeded: "badge-ok",
  failed: "badge-danger",
  running: "badge-warning",
  paused: "badge-warning",
  skipped: "badge-muted",
  draft: "badge-muted",
  active: "badge-ok",
};

const ANDROID_PAYLOAD = `{
  "event": "workflow.run",
  "title": "Stock bajo",
  "body": "Quedan 3 unidades",
  "sku": "ABC",
  "stock": 3,
  "workflow_id": "…",
  "run_id": "…"
}`;

export default function WorkflowsPage() {
  const { session } = useAuth();
  const [wfs, setWfs] = useState<WF[]>([]);
  const [tpls, setTpls] = useState<Tpl[]>([]);
  const [kbs, setKbs] = useState<KB[]>([]);
  const [agents, setAgents] = useState<Agent[]>([]);
  const [selected, setSelected] = useState<string | null>(null);
  const [runs, setRuns] = useState<Run[]>([]);
  const [steps, setSteps] = useState<StepRow[] | null>(null);
  const [name, setName] = useState("");
  const [root, setRoot] = useState<BlockNode>(() => makeBlock("hat_schedule", { every_minutes: "5" }));
  const [advanced, setAdvanced] = useState(false);
  const [rawJson, setRawJson] = useState("[]");
  const [payload, setPayload] = useState("{}");
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState("");
  const [error, setError] = useState("");
  const [hookSecret, setHookSecret] = useState("");
  const [hookUrl, setHookUrl] = useState("");
  const origin = typeof window !== "undefined" ? window.location.origin : "";

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
    void Promise.all([
      api<{ knowledge_bases: KB[] }>("/api/v1/knowledge-bases", { token: session.token, organizationId: session.organizationId }).catch(() => ({ knowledge_bases: [] as KB[] })),
      api<{ agents: Agent[] }>("/api/v1/agents", { token: session.token, organizationId: session.organizationId }).catch(() => ({ agents: [] as Agent[] })),
    ]).then(([kb, ag]) => {
      setKbs(kb.knowledge_bases || []);
      setAgents(ag.agents || []);
    });
  }

  useEffect(() => {
    void load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [session]);

  function irFromUi() {
    if (advanced) {
      const parsed = JSON.parse(rawJson || "[]");
      const steps = Array.isArray(parsed) ? parsed : [];
      return { trigger_type: "webhook" as const, trigger_config: {}, steps, editor_state: { blocks: root } };
    }
    return blocksToIr(root);
  }

  async function create() {
    if (!session || !name) return;
    setBusy("create");
    setError("");
    try {
      const ir = irFromUi();
      const out = await api<{ workflow_id: string; hook_secret?: string }>("/api/v1/workflows", {
        method: "POST",
        token: session.token,
        organizationId: session.organizationId,
        body: JSON.stringify({
          name,
          trigger_type: ir.trigger_type,
          trigger_config: ir.trigger_config,
          steps: ir.steps,
          editor_state: ir.editor_state,
        }),
      });
      if (out.hook_secret) setHookSecret(out.hook_secret);
      setHookUrl(`${origin}/api/v1/public/workflows/${out.workflow_id}/hook`);
      setName("");
      setRoot(makeBlock("hat_schedule", { every_minutes: "5" }));
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
    setError("");
    try {
      await api(`/api/v1/workflows/templates/${slug}/install`, { method: "POST", token: session.token, organizationId: session.organizationId });
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Error");
    } finally {
      setBusy("");
    }
  }

  async function select(id: string) {
    setSelected(id);
    setSteps(null);
    if (!session) return;
    const [r, d] = await Promise.all([
      api<{ runs: Run[] }>(`/api/v1/workflows/${id}/runs`, { token: session.token, organizationId: session.organizationId }),
      api<{
        steps: WorkflowStep[];
        trigger_type: string;
        trigger_config: Record<string, unknown>;
        editor_state?: { blocks?: BlockNode };
        hook_url?: string;
      }>(`/api/v1/workflows/${id}`, { token: session.token, organizationId: session.organizationId }),
    ]);
    setRuns(r.runs || []);
    setRoot(irToBlocks(d.trigger_type, d.trigger_config, d.steps, d.editor_state));
    setRawJson(JSON.stringify(d.steps || [], null, 2));
    setHookUrl(`${origin}${d.hook_url || `/api/v1/public/workflows/${id}/hook`}`);
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
      <PageHeader
        title="Workflow Automation"
        subtitle="Bloques tipo Scratch: schedule, API, KB, si/si no, email y webhook. El Android se engancha al webhook saliente."
      />
      {error && <ErrorInline>{error}</ErrorInline>}
      {hookSecret && (
        <div className="panel border-ok p-3 text-xs" data-testid="wf-hook-secret">
          <p className="font-semibold text-text">Secret inbound (una vez)</p>
          <p className="mt-1 font-mono text-[11px] text-text">{hookSecret}</p>
          <p className="mt-1 text-muted">Header: X-Zent-Workflow-Secret. URL: {hookUrl}</p>
          <button type="button" className="btn btn-ghost mt-1 min-h-7 text-[10px]" onClick={() => void navigator.clipboard.writeText(hookSecret)}>
            Copiar secret
          </button>
        </div>
      )}
      {loading ? (
        <SkeletonBlock className="h-64" />
      ) : (
        <div className="grid grid-cols-1 gap-6 lg:grid-cols-3">
          <section className="panel space-y-3 p-4 lg:col-span-3">
            <h2 className="flex items-center gap-2 text-sm font-semibold text-text">
              <Lightning size={14} /> Nuevo workflow
            </h2>
            <input
              className="w-full max-w-md rounded-md border border-border bg-soft px-2 py-2 text-sm"
              placeholder="nombre…"
              value={name}
              onChange={(e) => setName(e.target.value)}
            />
            <WorkflowBlockEditor root={root} onChange={setRoot} kbs={kbs} agents={agents} />
            <label className="flex items-center gap-2 text-xs text-muted">
              <input type="checkbox" checked={advanced} onChange={(e) => setAdvanced(e.target.checked)} />
              JSON avanzado
            </label>
            {advanced && (
              <textarea
                className="h-36 w-full rounded-md border border-border bg-soft px-2 py-2 font-mono text-[11px]"
                value={rawJson}
                onChange={(e) => setRawJson(e.target.value)}
              />
            )}
            <button type="button" className="btn btn-primary min-h-9 text-xs" disabled={!!busy || !name} onClick={() => void create()}>
              Crear
            </button>
            <div className="rounded-md border border-border p-3 text-[11px]" data-testid="wf-android-contract">
              <p className="font-semibold text-text">Contrato Android / webhook saliente</p>
              <p className="mt-1 text-muted">
                Suscríbete en Webhooks al evento workflow.run (firma X-Zent-Signature). Payload de ejemplo:
              </p>
              <pre className="mt-2 overflow-x-auto rounded-md bg-soft p-2 font-mono text-[10px] text-text">{ANDROID_PAYLOAD}</pre>
              <button
                type="button"
                className="btn btn-ghost mt-1 min-h-7 px-2 text-[10px]"
                onClick={() => void navigator.clipboard.writeText(ANDROID_PAYLOAD)}
              >
                Copiar payload
              </button>
              {hookUrl && <p className="mt-2 text-muted">Inbound: POST {hookUrl}</p>}
            </div>
            <h3 className="text-sm font-semibold text-text">Plantillas</h3>
            <div className="space-y-1">
              {tpls.map((t) => (
                <div key={t.slug} className="flex items-center gap-2 rounded-md bg-soft px-3 py-2 text-xs">
                  <SquaresFour size={12} className="text-faint" />
                  <span className="flex-1 text-text">{t.name}</span>
                  <span className="text-[10px] text-faint">{t.steps.length} pasos</span>
                  <button
                    type="button"
                    data-testid={`wf-install-${t.slug}`}
                    className="btn btn-ghost min-h-6 px-2 text-[10px]"
                    disabled={!!busy}
                    onClick={() => void install(t.slug)}
                  >
                    Instalar
                  </button>
                </div>
              ))}
            </div>
          </section>

          <section className="lg:col-span-3">
            <h2 className="mb-2 text-sm font-semibold text-text">Workflows ({wfs.length})</h2>
            <div className="panel space-y-2 p-3">
              {wfs.map((w) => (
                <div key={w.id} className={`rounded-md border p-3 ${selected === w.id ? "border-accent bg-accent/5" : "border-border bg-soft/50"}`}>
                  <div className="flex flex-wrap items-center gap-2">
                    <FlowArrow size={14} className="text-accent" />
                    <button type="button" className="text-sm font-medium text-text" onClick={() => void select(w.id)}>
                      {w.name}
                    </button>
                    <span className={`badge ${ST[w.status] ?? "badge-muted"}`}>{w.status}</span>
                    <span className="badge badge-muted">{w.trigger_type}</span>
                    <span className="flex-1" />
                    <span className="text-[10px] text-faint">
                      {w.ok_runs}/{w.runs} ok
                    </span>
                    <button type="button" className="btn btn-ghost min-h-7 px-2 text-[11px]" disabled={!!busy} onClick={() => void act(w.id, "run")}>
                      <Play size={11} /> Ejecutar
                    </button>
                    {w.status !== "active" ? (
                      <button type="button" className="btn btn-ghost min-h-7 px-2 text-[11px]" disabled={!!busy} onClick={() => void act(w.id, "activate")}>
                        Activar
                      </button>
                    ) : (
                      <button type="button" className="btn btn-ghost min-h-7 px-2 text-[11px]" disabled={!!busy} onClick={() => void act(w.id, "pause")}>
                        Pausar
                      </button>
                    )}
                  </div>
                  <div className="mt-1 flex gap-2">
                    <input
                      className="flex-1 rounded-md border border-border bg-soft px-2 py-1 font-mono text-[10px]"
                      placeholder='{"stock": "3"}'
                      value={payload}
                      onChange={(e) => setPayload(e.target.value)}
                    />
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
                      <span className="flex-1 text-text">
                        {r.id.slice(0, 8)}… · {new Date(r.started_at).toLocaleTimeString()}
                      </span>
                      <span className="text-faint">{r.duration_ms != null ? `${r.duration_ms}ms` : "—"}</span>
                      <button type="button" className="btn btn-ghost min-h-6 px-2 text-[10px]" onClick={() => void showRun(r.id)}>
                        pasos
                      </button>
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
                        <span className="font-medium text-text">
                          #{s.step_index} {s.step_type}
                        </span>
                        <span className="text-faint">
                          retries {s.retries} · {s.duration_ms ?? "—"}ms
                        </span>
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
