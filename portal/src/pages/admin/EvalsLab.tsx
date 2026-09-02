import { Flask, Play, Plus } from "@phosphor-icons/react";
import { useEffect, useState } from "react";
import { platformApi } from "../../api";
import {
  EmptyState,
  ErrorInline,
  PageHeader,
  SkeletonBlock,
} from "../../components/ui";
import { usePlatformAuth } from "../../platformAuth";

type Dataset = {
  id: string;
  organization_id: string;
  name: string;
  description: string | null;
  version: number;
  status: string;
  items: number;
  created_at: string;
};

type Run = {
  id: string;
  dataset_id: string;
  dataset_version: number;
  agent_id: string;
  model: string | null;
  status: string;
  score_overall: number | null;
  faithfulness: number | null;
  hallucination_rate: number | null;
  latency_p95: number | null;
  cost_total: number | null;
  passed_gate: boolean | null;
  regression: boolean;
  started_at: string;
};

export default function AdminEvalsLabPage() {
  const { session } = usePlatformAuth();
  const [datasets, setDatasets] = useState<Dataset[]>([]);
  const [runs, setRuns] = useState<Run[]>([]);
  const [orgs, setOrgs] = useState<{ id: string }[]>([]);
  const [agents, setAgents] = useState<Record<string, { id: string; name: string }[]>>({});
  const [dsForm, setDsForm] = useState({ organization_id: "", name: "", description: "" });
  const [itemForm, setItemForm] = useState({ dataset_id: "", question: "", expected_answer: "" });
  const [runForm, setRunForm] = useState({ organization_id: "", dataset_id: "", agent_id: "", auto_promote: false, auto_rollback: false });
  const [detail, setDetail] = useState<string>("");
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState("");
  const [error, setError] = useState("");

  async function load() {
    if (!session) return;
    setError("");
    try {
      const [d, r, o] = await Promise.all([
        platformApi<{ datasets: Dataset[] }>("/api/v1/platform/evals/datasets", { token: session.token }),
        platformApi<{ runs: Run[] }>("/api/v1/platform/evals/runs", { token: session.token }),
        platformApi<{ organizations: { id: string }[] }>("/api/v1/platform/organizations", { token: session.token }),
      ]);
      setDatasets(d.datasets || []);
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

  async function loadAgents(oid: string) {
    if (!session) return;
    try {
      const a = await platformApi<{ agents: { id: string; name: string }[] }>(
        `/api/v1/platform/organizations/${oid}/agents`,
        { token: session.token }
      );
      setAgents((prev) => ({ ...prev, [oid]: a.agents || [] }));
    } catch (e) {
      setError(e instanceof Error ? e.message : "Error");
    }
  }

  async function createDataset() {
    if (!session) return;
    setBusy("ds");
    setError("");
    try {
      await platformApi("/api/v1/platform/evals/datasets", {
        method: "POST",
        token: session.token,
        body: JSON.stringify(dsForm),
      });
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Error");
    } finally {
      setBusy("");
    }
  }

  async function addItems() {
    if (!session) return;
    setBusy("items");
    setError("");
    try {
      const out = await platformApi<{ version: number; items_added: number }>(
        `/api/v1/platform/evals/datasets/${itemForm.dataset_id}/items`,
        { method: "POST", token: session.token, body: JSON.stringify({ items: [{ question: itemForm.question, expected_answer: itemForm.expected_answer }] }) }
      );
      setError(`Items añadidos: ${out.items_added} (v${out.version})`);
      setItemForm({ dataset_id: "", question: "", expected_answer: "" });
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Error");
    } finally {
      setBusy("");
    }
  }

  async function triggerRun() {
    if (!session) return;
    setBusy("run");
    setError("");
    setDetail("");
    try {
      const out = await platformApi<{ status: string; run_id: string }>("/api/v1/platform/evals/runs", {
        method: "POST",
        token: session.token,
        body: JSON.stringify(runForm),
      });
      setError(`Run iniciado: ${out.run_id.slice(0, 8)}…`);
      setTimeout(() => void load(), 2000);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Error");
    } finally {
      setBusy("");
    }
  }

  async function showDetail(runId: string) {
    if (!session) return;
    setError("");
    try {
      const d = await platformApi<Record<string, unknown>>(`/api/v1/platform/evals/runs/${runId}`, {
        token: session.token,
      });
      setDetail(JSON.stringify(d, null, 2));
    } catch (e) {
      setError(e instanceof Error ? e.message : "Error");
    }
  }

  const gateBadge = (r: Run) =>
    r.status !== "completed" || r.passed_gate == null
      ? "badge-muted"
      : r.passed_gate
        ? "badge-ok"
        : "badge-danger";

  return (
    <div className="space-y-6">
      <PageHeader
        title="Evals Lab"
        subtitle="Datasets versionados, runs con gate de promo y detección de regresión."
      />
      {error && <ErrorInline>{error}</ErrorInline>}
      {loading ? (
        <SkeletonBlock className="h-40" />
      ) : (
        <>
          <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
            <section className="panel p-4">
              <h3 className="mb-2 flex items-center gap-2 text-sm font-semibold text-text">
                <Plus size={15} aria-hidden /> Dataset + items
              </h3>
              <div className="grid grid-cols-1 gap-2">
                <select className="rounded-md border border-border bg-soft px-2 py-2 text-sm" value={dsForm.organization_id} onChange={(e) => setDsForm((f) => ({ ...f, organization_id: e.target.value }))}>
                  <option value="">Org…</option>
                  {orgs.map((o) => (
                    <option key={o.id} value={o.id}>{o.id.slice(0, 8)}</option>
                  ))}
                </select>
                <input className="rounded-md border border-border bg-soft px-3 py-2 text-sm" placeholder="Nombre" value={dsForm.name} onChange={(e) => setDsForm((f) => ({ ...f, name: e.target.value }))} />
                <button type="button" className="btn btn-secondary min-h-9 text-xs" disabled={!!busy} onClick={() => void createDataset()}>
                  Crear dataset
                </button>
                <hr className="border-border" />
                <select className="rounded-md border border-border bg-soft px-2 py-2 text-sm" value={itemForm.dataset_id} onChange={(e) => setItemForm((f) => ({ ...f, dataset_id: e.target.value }))}>
                  <option value="">Dataset…</option>
                  {datasets.map((d) => (
                    <option key={d.id} value={d.id}>{d.name} (v{d.version})</option>
                  ))}
                </select>
                <input className="rounded-md border border-border bg-soft px-3 py-2 text-sm" placeholder="Pregunta" value={itemForm.question} onChange={(e) => setItemForm((f) => ({ ...f, question: e.target.value }))} />
                <input className="rounded-md border border-border bg-soft px-3 py-2 text-sm" placeholder="Respuesta esperada" value={itemForm.expected_answer} onChange={(e) => setItemForm((f) => ({ ...f, expected_answer: e.target.value }))} />
                <button type="button" className="btn btn-primary min-h-9 text-xs" disabled={!!busy} onClick={() => void addItems()}>
                  Añadir item (bump versión)
                </button>
              </div>
            </section>

            <section className="panel p-4">
              <h3 className="mb-2 flex items-center gap-2 text-sm font-semibold text-text">
                <Flask size={15} aria-hidden /> Ejecutar run
              </h3>
              <div className="grid grid-cols-1 gap-2">
                <select className="rounded-md border border-border bg-soft px-2 py-2 text-sm" value={runForm.organization_id} onChange={(e) => { setRunForm((f) => ({ ...f, organization_id: e.target.value })); void loadAgents(e.target.value); }}>
                  <option value="">Org…</option>
                  {orgs.map((o) => (
                    <option key={o.id} value={o.id}>{o.id.slice(0, 8)}</option>
                  ))}
                </select>
                <select className="rounded-md border border-border bg-soft px-2 py-2 text-sm" value={runForm.dataset_id} onChange={(e) => setRunForm((f) => ({ ...f, dataset_id: e.target.value }))}>
                  <option value="">Dataset…</option>
                  {datasets.filter((d) => !runForm.organization_id || d.organization_id === runForm.organization_id).map((d) => (
                    <option key={d.id} value={d.id}>{d.name} (v{d.version}, {d.items} items)</option>
                  ))}
                </select>
                <select className="rounded-md border border-border bg-soft px-2 py-2 text-sm" value={runForm.agent_id} onChange={(e) => setRunForm((f) => ({ ...f, agent_id: e.target.value }))}>
                  <option value="">Agente…</option>
                  {(agents[runForm.organization_id] ?? []).map((a) => (
                    <option key={a.id} value={a.id}>{a.name}</option>
                  ))}
                </select>
                <div className="flex items-center gap-4 text-xs">
                  <label className="flex items-center gap-1"><input type="checkbox" checked={runForm.auto_promote} onChange={(e) => setRunForm((f) => ({ ...f, auto_promote: e.target.checked }))} /> Auto-promote si pasa gate</label>
                  <label className="flex items-center gap-1"><input type="checkbox" checked={runForm.auto_rollback} onChange={(e) => setRunForm((f) => ({ ...f, auto_rollback: e.target.checked }))} /> Auto-rollback si regresión</label>
                </div>
                <button type="button" className="btn btn-primary min-h-9 text-xs" disabled={!!busy} onClick={() => void triggerRun()}>
                  <Play size={13} aria-hidden /> Ejecutar
                </button>
              </div>
            </section>
          </div>

          <section>
            <h3 className="mb-2 text-sm font-semibold text-text">Runs ({runs.length})</h3>
            <div className="panel overflow-x-auto">
              {runs.length === 0 ? (
                <EmptyState icon={Flask} title="Sin runs" body="Crea un dataset con items y ejecuta una evaluación." />
              ) : (
                <table className="table">
                  <thead>
                    <tr>
                      <th>Run</th>
                      <th>Dataset</th>
                      <th>Modelo</th>
                      <th>Score</th>
                      <th>Faith.</th>
                      <th>Halluc.</th>
                      <th>p95</th>
                      <th>Gate</th>
                      <th>Regresión</th>
                      <th className="text-right">Detalle</th>
                    </tr>
                  </thead>
                  <tbody>
                    {runs.map((r) => (
                      <tr key={r.id}>
                        <td className="mono text-xs">{r.id.slice(0, 8)}</td>
                        <td className="mono text-xs text-faint">{r.dataset_id.slice(0, 8)}·v{r.dataset_version}</td>
                        <td className="mono text-xs">{r.model ?? "—"}</td>
                        <td className="text-xs">{r.score_overall ?? "—"}</td>
                        <td className="text-xs">{r.faithfulness ?? "—"}</td>
                        <td className="text-xs">{r.hallucination_rate ?? "—"}</td>
                        <td className="text-xs">{r.latency_p95 != null ? `${r.latency_p95.toFixed(0)}ms` : "—"}</td>
                        <td>
                          <span className={`badge ${gateBadge(r)}`}>
                            {r.status !== "completed" ? r.status : r.passed_gate ? "PASS" : "FAIL"}
                          </span>
                        </td>
                        <td>{r.regression ? <span className="badge badge-danger">regresión</span> : <span className="text-xs text-faint">—</span>}</td>
                        <td className="text-right">
                          <button type="button" className="btn btn-ghost min-h-8 px-2 text-xs" onClick={() => void showDetail(r.id)}>
                            Ver
                          </button>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
            </div>
          </section>

          {detail && (
            <section className="panel p-4">
              <h3 className="mb-2 text-sm font-semibold text-text">Detalle del run</h3>
              <pre className="max-h-96 overflow-auto whitespace-pre-wrap rounded-md bg-soft p-3 text-[11px] text-text">{detail}</pre>
            </section>
          )}
        </>
      )}
    </div>
  );
}