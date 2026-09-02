import { GitBranch } from "@phosphor-icons/react";
import { useEffect, useState } from "react";
import { platformApi } from "../../api";
import { ErrorInline, PageHeader, SkeletonBlock } from "../../components/ui";
import { usePlatformAuth } from "../../platformAuth";

type Trace = {
  id: string;
  organization_id: string;
  agent_id: string | null;
  trace_id: string;
  status: string;
  model: string | null;
  input: string;
  total_latency_ms: number;
  total_tokens: number;
  cost: number;
  started_at: string;
};

type Span = { id: string; stage: string; name: string; status: string; started_ms: number; duration_ms: number; tokens: number; metadata: Record<string, unknown> };
type TraceDetail = Trace & { output: string | null; error: string | null; spans: Span[] };
type Compare = {
  same_input: boolean;
  a: { trace_id: string; status: string; model: string | null; latency_ms: number; tokens: number; cost: number; spans_count: number; error: string | null };
  b: { trace_id: string; status: string; model: string | null; latency_ms: number; tokens: number; cost: number; spans_count: number; error: string | null };
  deltas: { latency_ms: number; tokens: number; cost: number; spans_count: number };
  spans_diff: { stage: string; a_duration_ms: number | null; b_duration_ms: number | null; a_tokens: number | null; b_tokens: number | null }[];
  output_a: string;
  output_b: string;
};
type Stage = { stage: string; spans: number; avg_duration_ms: number; p95_duration_ms: number; tokens: number; errors: number; error_rate: number };

const STAGE_COLOR: Record<string, string> = { llm: "bg-blue-500", retrieval: "bg-emerald-500", tool: "bg-amber-500", rerank: "bg-purple-500", total: "bg-slate-400" };

export default function AdminTracesPage() {
  const { session } = usePlatformAuth();
  const [traces, setTraces] = useState<Trace[]>([]);
  const [stages, setStages] = useState<Stage[]>([]);
  const [detail, setDetail] = useState<TraceDetail | null>(null);
  const [compare, setCompare] = useState<Compare | null>(null);
  const [usage, setUsage] = useState<{ usage_events: unknown[]; api_logs: unknown[] } | null>(null);
  const [orgs, setOrgs] = useState<{ id: string }[]>([]);
  const [filters, setFilters] = useState({ organization_id: "", status: "", model: "", q: "" });
  const [selA, setSelA] = useState("");
  const [selB, setSelB] = useState("");
  const [hours, setHours] = useState(24);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  async function loadAll() {
    if (!session) return;
    setError("");
    try {
      const params = new URLSearchParams();
      if (filters.organization_id) params.set("organization_id", filters.organization_id);
      if (filters.status) params.set("status", filters.status);
      if (filters.model) params.set("model", filters.model);
      if (filters.q) params.set("q", filters.q);
      params.set("hours", String(hours));
      const [t, s] = await Promise.all([
        platformApi<{ traces: Trace[] }>(`/api/v1/platform/observability/traces?${params}`, { token: session.token }),
        platformApi<{ stages: Stage[] }>(`/api/v1/platform/observability/stages?hours=${hours}`, { token: session.token }),
      ]);
      setTraces(t.traces || []);
      setStages(s.stages || []);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Error");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    if (!session) return;
    (async () => {
      try {
        const o = await platformApi<{ organizations: { id: string }[] }>("/api/v1/platform/organizations", { token: session.token });
        setOrgs(o.organizations || []);
      } catch (e) {
        setError(e instanceof Error ? e.message : "Error");
      }
      await loadAll();
    })();
    const id = setInterval(() => void loadAll(), 10000);
    return () => clearInterval(id);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [session, hours]);

  async function showDetail(traceId: string) {
    if (!session) return;
    setError("");
    try {
      const [d, u] = await Promise.all([
        platformApi<TraceDetail>(`/api/v1/platform/observability/traces/${traceId}`, { token: session.token }),
        platformApi<{ usage_events: unknown[]; api_logs: unknown[] }>(`/api/v1/platform/observability/traces/${traceId}/usage`, { token: session.token }),
      ]);
      setDetail(d);
      setUsage(u);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Error");
    }
  }

  async function doCompare() {
    if (!session || !selA || !selB) return;
    setError("");
    try {
      const c = await platformApi<Compare>(`/api/v1/platform/observability/traces/compare?a=${selA}&b=${selB}`, { token: session.token });
      setCompare(c);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Error");
    }
  }

  const maxSpan = Math.max(...(detail?.spans ?? []).map((s) => s.duration_ms), 1);

  return (
    <div className="space-y-6">
      <PageHeader title="Traces & Spans" subtitle="Trazado distribuido de runs, comparación side-by-side y correlación con billing." />
      {error && <ErrorInline>{error}</ErrorInline>}
      {loading ? (
        <SkeletonBlock className="h-40" />
      ) : (
        <>
          <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
            {stages.map((s) => (
              <div key={s.stage} className="panel p-3">
                <p className="flex items-center gap-1 text-[11px] font-medium text-text">
                  <span className={`h-2 w-2 rounded-full ${STAGE_COLOR[s.stage] ?? "bg-slate-300"}`} />
                  {s.stage} ({s.spans})
                </p>
                <p className="stat-value">{s.avg_duration_ms.toFixed(0)}ms</p>
                <p className="text-[10px] text-faint">p95 {s.p95_duration_ms.toFixed(0)}ms · {s.errors} err · {s.tokens} tok</p>
              </div>
            ))}
          </div>

          <div className="flex flex-wrap items-center gap-2">
            <select className="rounded-md border border-border bg-soft px-2 py-1.5 text-xs" value={filters.organization_id} onChange={(e) => setFilters((f) => ({ ...f, organization_id: e.target.value }))}>
              <option value="">todas las orgs</option>
              {orgs.map((o) => (<option key={o.id} value={o.id}>{o.id.slice(0, 8)}</option>))}
            </select>
            <select className="rounded-md border border-border bg-soft px-2 py-1.5 text-xs" value={filters.status} onChange={(e) => setFilters((f) => ({ ...f, status: e.target.value }))}>
              <option value="">todos</option>
              {["completed", "error", "limit_reached"].map((s) => (<option key={s} value={s}>{s}</option>))}
            </select>
            <input className="rounded-md border border-border bg-soft px-2 py-1.5 text-xs" placeholder="modelo" value={filters.model} onChange={(e) => setFilters((f) => ({ ...f, model: e.target.value }))} />
            <input className="rounded-md border border-border bg-soft px-2 py-1.5 text-xs" placeholder="buscar en input/output…" value={filters.q} onChange={(e) => setFilters((f) => ({ ...f, q: e.target.value }))} />
            <button type="button" className="btn btn-primary min-h-8 text-xs" onClick={() => void loadAll()}>Filtrar</button>
            {[1, 24, 168].map((h) => (
              <button key={h} type="button" onClick={() => setHours(h)} className={`btn min-h-8 px-2 text-xs ${hours === h ? "btn-primary" : "btn-secondary"}`}>{h === 168 ? "7d" : `${h}h`}</button>
            ))}
          </div>

          <div className="grid grid-cols-1 gap-6 lg:grid-cols-3">
            <section className="lg:col-span-2">
              <div className="mb-2 flex items-center gap-2">
                <h3 className="text-sm font-semibold text-text">Traces ({traces.length})</h3>
                <select className="rounded-md border border-border bg-soft px-2 py-1.5 text-xs" value={selA} onChange={(e) => setSelA(e.target.value)}>
                  <option value="">A…</option>
                  {traces.slice(0, 30).map((t) => (<option key={t.id} value={t.trace_id}>{t.trace_id.slice(0, 12)} · {t.input?.slice(0, 40)}</option>))}
                </select>
                <select className="rounded-md border border-border bg-soft px-2 py-1.5 text-xs" value={selB} onChange={(e) => setSelB(e.target.value)}>
                  <option value="">B…</option>
                  {traces.slice(0, 30).map((t) => (<option key={t.id} value={t.trace_id}>{t.trace_id.slice(0, 12)} · {t.input?.slice(0, 40)}</option>))}
                </select>
                <button type="button" className="btn btn-secondary min-h-8 px-2 text-xs" disabled={!selA || !selB} onClick={() => void doCompare()}>
                  <GitBranch size={12} aria-hidden /> Comparar
                </button>
              </div>
              <div className="panel overflow-x-auto">
                <table className="table">
                  <thead>
                    <tr>
                      <th>Trace</th>
                      <th>Estado</th>
                      <th>Modelo</th>
                      <th>Input</th>
                      <th>Latencia</th>
                      <th>Tokens</th>
                      <th>Costo</th>
                      <th className="text-right">Detalle</th>
                    </tr>
                  </thead>
                  <tbody>
                    {traces.map((t) => (
                      <tr key={t.id}>
                        <td className="mono text-[10px] text-faint">{t.trace_id.slice(0, 12)}</td>
                        <td><span className={`badge ${t.status === "completed" ? "badge-ok" : t.status === "error" ? "badge-danger" : "badge-warning"}`}>{t.status}</span></td>
                        <td className="mono text-xs">{t.model ?? "—"}</td>
                        <td className="max-w-52 truncate text-[10px] text-faint" title={t.input}>{t.input}</td>
                        <td className="text-xs">{t.total_latency_ms.toFixed(0)}ms</td>
                        <td className="text-xs">{t.total_tokens}</td>
                        <td className="text-xs">${t.cost.toFixed(4)}</td>
                        <td className="text-right">
                          <button type="button" className="btn btn-ghost min-h-8 px-2 text-xs" onClick={() => void showDetail(t.trace_id)}>Ver</button>
                        </td>
                      </tr>
                    ))}
                    {traces.length === 0 && <tr><td colSpan={8} className="p-4 text-center text-xs text-faint">Sin trazas.</td></tr>}
                  </tbody>
                </table>
              </div>
            </section>

            {detail && (
              <section className="panel p-4">
                <h3 className="mb-2 text-sm font-semibold text-text">Spans · {detail.trace_id.slice(0, 12)}</h3>
                <p className="mb-2 max-h-16 overflow-auto rounded-md bg-soft p-2 text-[10px] text-faint">{detail.input}</p>
                <p className="mb-2 max-h-24 overflow-auto rounded-md bg-soft p-2 text-[10px] text-text">{detail.output ?? "—"}</p>
                <div className="space-y-1">
                  {detail.spans.map((s) => (
                    <div key={s.id} className="rounded-md bg-soft px-3 py-1.5 text-[11px]">
                      <div className="flex items-center justify-between">
                        <span className="flex items-center gap-1 truncate text-text">
                          <span className={`h-1.5 w-1.5 rounded-full ${STAGE_COLOR[s.stage] ?? "bg-slate-300"}`} />
                          {s.stage} · {s.name}
                        </span>
                        <span className="mono text-faint">{s.duration_ms.toFixed(0)}ms · {s.tokens} tok</span>
                      </div>
                      <div className="mt-1 h-1 rounded-full bg-soft">
                        <div className={`h-1 rounded-full ${STAGE_COLOR[s.stage] ?? "bg-slate-300"}`} style={{ width: `${(s.duration_ms / maxSpan) * 100}%` }} />
                      </div>
                    </div>
                  ))}
                </div>
                <h4 className="mb-1 mt-3 text-[11px] font-semibold text-text">Correlación</h4>
                <p className="text-[10px] text-faint">{usage?.usage_events.length ?? 0} usage events · {usage?.api_logs.length ?? 0} api logs</p>
              </section>
            )}
          </div>

          {compare && (
            <section className="panel p-4">
              <h3 className="mb-2 text-sm font-semibold text-text">
                Comparación {compare.same_input ? "(mismo input)" : "(inputs distintos)"}
              </h3>
              <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
                <div className="rounded-md bg-soft p-3 text-xs">
                  <p className="mono font-medium text-text">A · {compare.a.trace_id.slice(0, 12)}</p>
                  <p>estado {compare.a.status} · {compare.a.model} · {compare.a.latency_ms.toFixed(0)}ms · {compare.a.tokens} tok · ${compare.a.cost.toFixed(4)}</p>
                  <p className="mt-1 max-h-20 overflow-auto text-[10px] text-faint">{compare.output_a}</p>
                </div>
                <div className="rounded-md bg-soft p-3 text-xs">
                  <p className="mono font-medium text-text">B · {compare.b.trace_id.slice(0, 12)}</p>
                  <p>estado {compare.b.status} · {compare.b.model} · {compare.b.latency_ms.toFixed(0)}ms · {compare.b.tokens} tok · ${compare.b.cost.toFixed(4)}</p>
                  <p className="mt-1 max-h-20 overflow-auto text-[10px] text-faint">{compare.output_b}</p>
                </div>
              </div>
              <p className="mt-2 text-[11px] text-faint">
                Δ latencia <span className={compare.deltas.latency_ms > 0 ? "text-red-400" : "text-emerald-400"}>{compare.deltas.latency_ms > 0 ? "+" : ""}{compare.deltas.latency_ms.toFixed(0)}ms</span> · Δ tokens {compare.deltas.tokens > 0 ? "+" : ""}{compare.deltas.tokens} · Δ costo ${compare.deltas.cost.toFixed(4)}
              </p>
              <div className="mt-2 space-y-1">
                {compare.spans_diff.map((s) => (
                  <div key={s.stage} className="flex items-center justify-between rounded-md bg-soft px-3 py-1 text-[11px]">
                    <span className="text-text">{s.stage}</span>
                    <span className="mono text-faint">A: {s.a_duration_ms != null ? `${s.a_duration_ms.toFixed(0)}ms` : "—"}</span>
                    <span className="mono text-faint">B: {s.b_duration_ms != null ? `${s.b_duration_ms.toFixed(0)}ms` : "—"}</span>
                  </div>
                ))}
              </div>
            </section>
          )}
        </>
      )}
    </div>
  );
}