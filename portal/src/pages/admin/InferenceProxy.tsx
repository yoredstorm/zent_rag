import { ListMagnifyingGlass, Plus } from "@phosphor-icons/react";
import { useEffect, useState } from "react";
import { platformApi } from "../../api";
import { ErrorInline, PageHeader, SkeletonBlock } from "../../components/ui";
import { usePlatformAuth } from "../../platformAuth";

type Model = {
  id: string;
  model_name: string;
  backend: string;
  capacity: number;
  status: string;
};

type Perf = {
  model: string;
  backend: string;
  requests: number;
  tokens: number;
  cost: number;
  avg_latency_ms: number;
  p95_latency_ms: number;
  avg_queue_ms: number;
  throughput_per_min: number;
  errors: number;
};

type Log = {
  id: string;
  model: string;
  backend: string;
  status: string;
  total_tokens: number;
  latency_ms: number;
  queue_wait_ms: number;
  cost: number;
  created_at: string;
};

type Queue = { plan: string; model: string; depth: number; priority: number };

export default function AdminInferenceProxyPage() {
  const { session } = usePlatformAuth();
  const [models, setModels] = useState<Model[]>([]);
  const [perf, setPerf] = useState<Perf[]>([]);
  const [logs, setLogs] = useState<Log[]>([]);
  const [queue, setQueue] = useState<Queue[]>([]);
  const [hours, setHours] = useState(24);
  const [modelFilter, setModelFilter] = useState("");
  const [modelForm, setModelForm] = useState({ model_name: "", backend: "openai", capacity: 50 });
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState("");
  const [error, setError] = useState("");

  async function load() {
    if (!session) return;
    setError("");
    try {
      const [m, p, l, q] = await Promise.all([
        platformApi<{ models: Model[] }>("/api/v1/platform/proxy/models", { token: session.token }),
        platformApi<{ models: Perf[] }>(`/api/v1/platform/proxy/performance?hours=${hours}`, { token: session.token }),
        platformApi<{ logs: Log[] }>("/api/v1/platform/proxy/inference-logs?hours=24&limit=50", { token: session.token }),
        platformApi<{ queues: Queue[] }>("/api/v1/platform/proxy/queue", { token: session.token }),
      ]);
      setModels(m.models || []);
      setPerf(p.models || []);
      setLogs(l.logs || []);
      setQueue(q.queues || []);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Error");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    void load();
    const id = setInterval(() => void load(), 8000);
    return () => clearInterval(id);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [session, hours]);

  async function upsertModel() {
    if (!session) return;
    setBusy("model");
    setError("");
    try {
      await platformApi("/api/v1/platform/proxy/models", {
        method: "POST",
        token: session.token,
        body: JSON.stringify(modelForm),
      });
      setModelForm({ model_name: "", backend: "openai", capacity: 50 });
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Error");
    } finally {
      setBusy("");
    }
  }

  const shown = perf.filter((p) => !modelFilter || p.model === modelFilter);

  return (
    <div className="space-y-6">
      <PageHeader title="Inference Proxy" subtitle="Cola por plan, routing por capacidad, logs e inferencia y performance por modelo." />
      {error && <ErrorInline>{error}</ErrorInline>}
      {loading ? (
        <SkeletonBlock className="h-40" />
      ) : (
        <>
          <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
            {shown.map((p) => (
              <div key={p.model} className="panel p-4">
                <div className="flex items-baseline justify-between">
                  <p className="mono text-sm font-semibold text-text">{p.model}</p>
                  <span className="badge badge-muted">{p.backend}</span>
                </div>
                <p className="mt-2 text-[11px] text-faint">p95 <span className="text-text">{p.p95_latency_ms.toFixed(0)}ms</span> · avg {p.avg_latency_ms.toFixed(0)}ms · cola {p.avg_queue_ms.toFixed(0)}ms</p>
                <p className="text-[11px] text-faint">{p.requests} req ({p.throughput_per_min}/min) · {p.errors} err · ${p.cost.toFixed(3)}</p>
              </div>
            ))}
            {shown.length === 0 && (
              <div className="panel p-4 text-xs text-faint">Sin tráfico en la ventana.</div>
            )}
          </div>

          <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
            <section className="panel p-4">
              <h3 className="mb-2 flex items-center gap-2 text-sm font-semibold text-text">
                <ListMagnifyingGlass size={15} aria-hidden /> Cola viva por plan
              </h3>
              <div className="space-y-1">
                {queue.length === 0 && <p className="text-xs text-faint">Cola vacía.</p>}
                {queue.map((q) => (
                  <div key={`${q.plan}:${q.model}`} className="flex items-center justify-between rounded-md bg-soft px-3 py-1.5 text-xs">
                    <span className="font-medium text-text">{q.plan}</span>
                    <span className="mono text-faint">{q.model}</span>
                    <span className={`badge ${q.depth > 10 ? "badge-danger" : "badge-muted"}`}>{q.depth} esperando</span>
                  </div>
                ))}
              </div>
              <h3 className="mb-2 mt-4 flex items-center gap-2 text-sm font-semibold text-text">
                <Plus size={15} aria-hidden /> Modelo del proxy
              </h3>
              <div className="grid grid-cols-2 gap-2">
                <input className="rounded-md border border-border bg-soft px-3 py-2 text-sm" placeholder="modelo (ej. zent-fast)" value={modelForm.model_name} onChange={(e) => setModelForm((f) => ({ ...f, model_name: e.target.value }))} />
                <select className="rounded-md border border-border bg-soft px-2 py-2 text-sm" value={modelForm.backend} onChange={(e) => setModelForm((f) => ({ ...f, backend: e.target.value }))}>
                  {["openai", "vllm", "tgi"].map((b) => (<option key={b} value={b}>{b}</option>))}
                </select>
                <input type="number" className="rounded-md border border-border bg-soft px-3 py-2 text-sm" placeholder="capacidad" value={modelForm.capacity} onChange={(e) => setModelForm((f) => ({ ...f, capacity: Number(e.target.value) }))} />
                <button type="button" className="btn btn-primary min-h-9 text-xs" disabled={!!busy} onClick={() => void upsertModel()}>Guardar</button>
              </div>
            </section>

            <section className="panel p-4">
              <h3 className="mb-2 flex items-center gap-2 text-sm font-semibold text-text">Catálogo</h3>
              <div className="overflow-x-auto">
                <table className="table">
                  <thead>
                    <tr><th>Modelo</th><th>Backend</th><th>Capacidad</th><th>Estado</th></tr>
                  </thead>
                  <tbody>
                    {models.map((m) => (
                      <tr key={m.id}>
                        <td className="mono text-xs">{m.model_name}</td>
                        <td className="text-xs">{m.backend}</td>
                        <td className="text-xs">{m.capacity}</td>
                        <td><span className={`badge ${m.status === "active" ? "badge-ok" : "badge-muted"}`}>{m.status}</span></td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              <div className="mt-3 flex items-center gap-2">
                <label className="text-xs text-faint">Ventana:</label>
                {[1, 6, 24].map((h) => (
                  <button key={h} type="button" onClick={() => setHours(h)} className={`btn min-h-8 px-3 text-xs ${hours === h ? "btn-primary" : "btn-secondary"}`}>{h}h</button>
                ))}
                <select className="ml-2 rounded-md border border-border bg-soft px-2 py-1.5 text-xs" value={modelFilter} onChange={(e) => setModelFilter(e.target.value)}>
                  <option value="">todos los modelos</option>
                  {perf.map((p) => (<option key={p.model} value={p.model}>{p.model}</option>))}
                </select>
              </div>
            </section>
          </div>

          <section>
            <h3 className="mb-2 text-sm font-semibold text-text">Logs de inferencia (últimas 50)</h3>
            <div className="panel overflow-x-auto">
              <table className="table">
                <thead>
                  <tr>
                    <th>Hora</th>
                    <th>Modelo</th>
                    <th>Backend</th>
                    <th>Tokens</th>
                    <th>Latencia</th>
                    <th>Cola</th>
                    <th>Costo</th>
                    <th>Estado</th>
                  </tr>
                </thead>
                <tbody>
                  {logs.map((l) => (
                    <tr key={l.id}>
                      <td className="mono text-[10px] text-faint">{new Date(l.created_at).toLocaleTimeString()}</td>
                      <td className="mono text-xs">{l.model}</td>
                      <td className="text-xs">{l.backend}</td>
                      <td className="text-xs">{l.total_tokens}</td>
                      <td className="text-xs">{l.latency_ms.toFixed(0)}ms</td>
                      <td className="text-xs">{l.queue_wait_ms.toFixed(0)}ms</td>
                      <td className="text-xs">${l.cost.toFixed(5)}</td>
                      <td><span className={`badge ${l.status === "completed" ? "badge-ok" : "badge-danger"}`}>{l.status}</span></td>
                    </tr>
                  ))}
                  {logs.length === 0 && <tr><td colSpan={8} className="p-4 text-center text-xs text-faint">Sin logs en la ventana.</td></tr>}
                </tbody>
              </table>
            </div>
          </section>
        </>
      )}
    </div>
  );
}