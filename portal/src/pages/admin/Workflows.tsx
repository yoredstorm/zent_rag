import { CheckCircle, Play, Plus, XCircle } from "@phosphor-icons/react";
import { useEffect, useState } from "react";
import { platformApi } from "../../api";
import {
  EmptyState,
  ErrorInline,
  PageHeader,
  SkeletonBlock,
} from "../../components/ui";
import { usePlatformAuth } from "../../platformAuth";

type Workflow = {
  id: string;
  organization_id: string;
  name: string;
  description: string | null;
  enabled: boolean;
  trigger_type: string;
  cron_expr: string | null;
  steps: { type: string; params: Record<string, unknown> }[];
  created_at: string;
  last_run_at: string | null;
};

type Run = {
  id: string;
  workflow_id: string;
  organization_id: string;
  trigger: string;
  status: string;
  current_step: number;
  started_at: string;
  completed_at: string | null;
  error: string | null;
};

export default function AdminWorkflowsPage() {
  const { session } = usePlatformAuth();
  const [workflows, setWorkflows] = useState<Workflow[]>([]);
  const [runs, setRuns] = useState<Run[]>([]);
  const [showCreate, setShowCreate] = useState(false);
  const [form, setForm] = useState({
    organization_id: "",
    name: "",
    trigger_type: "manual",
    cron_expr: "",
    steps: "[\n  { \"type\": \"notify\", \"params\": { \"email\": \"ops@corp.example\", \"message\": \"Pipeline ejecutado\" } }\n]",
  });
  const [orgs, setOrgs] = useState<{ id: string }[]>([]);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState("");
  const [error, setError] = useState("");

  async function load() {
    if (!session) return;
    setError("");
    try {
      const [w, r, o] = await Promise.all([
        platformApi<{ workflows: Workflow[] }>("/api/v1/platform/workflows", { token: session.token }),
        platformApi<{ runs: Run[] }>("/api/v1/platform/workflows/runs", { token: session.token }),
        platformApi<{ organizations: { id: string }[] }>("/api/v1/platform/organizations", {
          token: session.token,
        }),
      ]);
      setWorkflows(w.workflows || []);
      setRuns(r.runs || []);
      setOrgs(o.organizations || []);
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

  async function createWorkflow() {
    if (!session) return;
    setBusy("create");
    setError("");
    try {
      let steps: unknown[];
      try {
        steps = JSON.parse(form.steps);
      } catch {
        setError("Steps: JSON inválido");
        return;
      }
      const body = {
        name: form.name,
        trigger_type: form.trigger_type,
        cron_expr: form.cron_expr || null,
        steps,
      };
      await platformApi("/api/v1/platform/workflows", {
        method: "POST",
        token: session.token,
        body: JSON.stringify(body),
      });
      setShowCreate(false);
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Error");
    } finally {
      setBusy("");
    }
  }

  async function trigger(workflowId: string) {
    if (!session) return;
    setBusy(workflowId);
    setError("");
    try {
      const out = await platformApi<{ status: string; run_id: string }>(
        `/api/v1/platform/workflows/${workflowId}/trigger`,
        { method: "POST", token: session.token, body: "{}" }
      );
      setError(`Run iniciado: ${out.run_id.slice(0, 8)}… (${out.status})`);
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Error");
    } finally {
      setBusy("");
    }
  }

  const statusBadge = (s: string) =>
    s === "completed" ? "badge-ok" : s === "running" ? "badge-pending" : s === "failed" ? "badge-danger" : "badge-muted";

  return (
    <div className="space-y-6">
      <PageHeader
        title="Workflows"
        subtitle="Pipelines multi-paso: ingest → evaluate → deploy → notify, con aprobaciones y cron."
        actions={
          <button type="button" className="btn btn-primary min-h-11" onClick={() => setShowCreate((s) => !s)}>
            <Plus size={15} aria-hidden /> Nuevo workflow
          </button>
        }
      />
      {error && <ErrorInline>{error}</ErrorInline>}
      {showCreate && (
        <div className="panel grid grid-cols-1 gap-3 p-4 lg:grid-cols-3">
          <input
            className="rounded-md border border-border bg-soft px-3 py-2 text-sm"
            placeholder="Nombre"
            value={form.name}
            onChange={(e) => setForm((f) => ({ ...f, name: e.target.value }))}
          />
          <select
            className="rounded-md border border-border bg-soft px-2 py-2 text-sm"
            value={form.trigger_type}
            onChange={(e) => setForm((f) => ({ ...f, trigger_type: e.target.value }))}
          >
            <option value="manual">Manual</option>
            <option value="schedule">Schedule (cron)</option>
            <option value="event">Evento</option>
          </select>
          <input
            className="rounded-md border border-border bg-soft px-3 py-2 text-sm"
            placeholder="cron (ej: 0 * * * *)"
            value={form.cron_expr}
            onChange={(e) => setForm((f) => ({ ...f, cron_expr: e.target.value }))}
          />
          <textarea
            className="col-span-full min-h-32 rounded-md border border-border bg-soft px-3 py-2 font-mono text-xs text-text"
            value={form.steps}
            onChange={(e) => setForm((f) => ({ ...f, steps: e.target.value }))}
          />
          <div className="col-span-full">
            <button type="button" className="btn btn-primary min-h-9 text-xs" disabled={!!busy} onClick={() => void createWorkflow()}>
              Crear (tenant API)
            </button>
          </div>
        </div>
      )}

      <section>
        <h3 className="mb-2 text-sm font-semibold text-text">Definiciones</h3>
        <div className="grid grid-cols-1 gap-3 lg:grid-cols-2 xl:grid-cols-3">
          {workflows.length === 0 ? (
            <div className="panel col-span-full">
              <EmptyState icon={Play} title="Sin workflows" body="Crea uno vía POST /api/v1/workflows (tenant)." />
            </div>
          ) : (
            workflows.map((w) => (
              <div key={w.id} className="panel flex flex-col gap-2 p-4">
                <div className="flex items-center justify-between">
                  <p className="text-sm font-semibold text-text">{w.name}</p>
                  <span className={`badge ${w.enabled ? "badge-ok" : "badge-muted"}`}>
                    {w.trigger_type}
                    {w.cron_expr ? ` · ${w.cron_expr}` : ""}
                  </span>
                </div>
                <p className="text-xs text-faint">org {w.organization_id.slice(0, 8)}… · {w.steps.length} pasos</p>
                <p className="flex flex-wrap gap-1">
                  {w.steps.map((s, i) => (
                    <span key={i} className="badge badge-muted">
                      {i + 1}. {s.type}
                    </span>
                  ))}
                </p>
                <button
                  type="button"
                  className="btn btn-secondary mt-auto min-h-9 text-xs"
                  disabled={!!busy}
                  onClick={() => void trigger(w.id)}
                >
                  <Play size={12} aria-hidden /> Disparar
                </button>
              </div>
            ))
          )}
        </div>
      </section>

      <section>
        <h3 className="mb-2 text-sm font-semibold text-text">Runs ({runs.length})</h3>
        <div className="panel overflow-x-auto">
          <table className="table">
            <thead>
              <tr>
                <th>Run</th>
                <th>Workflow</th>
                <th>Trigger</th>
                <th>Estado</th>
                <th>Paso</th>
                <th>Iniciado</th>
                <th>Error</th>
              </tr>
            </thead>
            <tbody>
              {runs.map((r) => (
                <tr key={r.id}>
                  <td className="mono text-xs">{r.id.slice(0, 8)}</td>
                  <td className="mono text-xs text-faint">{r.workflow_id.slice(0, 8)}</td>
                  <td className="text-xs">{r.trigger}</td>
                  <td>
                    <span className={`badge ${statusBadge(r.status)}`}>
                      {r.status === "completed" && <CheckCircle size={12} className="mr-1 inline" aria-hidden />}
                      {r.status === "failed" && <XCircle size={12} className="mr-1 inline" aria-hidden />}
                      {r.status}
                    </span>
                  </td>
                  <td className="text-xs">{r.current_step}</td>
                  <td className="text-xs text-muted">{new Date(r.started_at).toLocaleString("es-PE")}</td>
                  <td className="max-w-48 truncate text-xs text-danger">{r.error ?? "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>
    </div>
  );
}