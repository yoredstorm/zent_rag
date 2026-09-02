import { Warning } from "@phosphor-icons/react";
import { useEffect, useState } from "react";
import { platformApi } from "../../api";
import { ErrorInline, PageHeader, SkeletonBlock } from "../../components/ui";
import { usePlatformAuth } from "../../platformAuth";

type Replica = {
  id: string;
  kind: string;
  endpoint: string;
  healthy: boolean;
  last_latency_ms: number | null;
  last_health_at: string | null;
};

type Region = {
  id: string;
  code: string;
  name: string;
  status: string;
  priority: number;
  replicas: Replica[];
};

type RegionLatency = { region: string; requests: number; avg_latency_ms: number; p95_latency_ms: number };

export default function AdminRegionsPage() {
  const { session } = usePlatformAuth();
  const [regions, setRegions] = useState<Region[]>([]);
  const [latency, setLatency] = useState<RegionLatency[]>([]);
  const [cache, setCache] = useState<{ hits: number; misses: number; total: number; hit_ratio: number } | null>(null);
  const [orgs, setOrgs] = useState<{ id: string }[]>([]);
  const [selectedOrg, setSelectedOrg] = useState("");
  const [resolution, setResolution] = useState<Record<string, unknown> | null>(null);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState("");
  const [error, setError] = useState("");

  async function load() {
    if (!session) return;
    setError("");
    try {
      const [r, l, c] = await Promise.all([
        platformApi<{ regions: Region[] }>("/api/v1/platform/regions", { token: session.token }),
        platformApi<{ regions: RegionLatency[] }>("/api/v1/platform/regions/latency?hours=24", { token: session.token }),
        platformApi<{ hits: number; misses: number; total: number; hit_ratio: number }>("/api/v1/platform/edge/cache/stats", { token: session.token }),
      ]);
      setRegions(r.regions || []);
      setLatency(l.regions || []);
      setCache(c);
      const o = await platformApi<{ organizations: { id: string }[] }>("/api/v1/platform/organizations", { token: session.token });
      setOrgs(o.organizations || []);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Error");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    void load();
    const id = setInterval(() => void load(), 15000);
    return () => clearInterval(id);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [session]);

  async function resolve(oid: string) {
    if (!session) return;
    setBusy("resolve");
    setError("");
    try {
      const res = await platformApi<Record<string, unknown>>(
        `/api/v1/platform/regions/resolve?organization_id=${oid}`,
        { token: session.token }
      );
      setResolution(res);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Error");
    } finally {
      setBusy("");
    }
  }

  async function failover(code: string) {
    if (!session || !selectedOrg) return;
    setBusy(code);
    setError("");
    try {
      const res = await platformApi<{ simulated_unhealthy: string; resolution: Record<string, unknown> }>(
        `/api/v1/platform/regions/${code}/failover?organization_id=${selectedOrg}`,
        { method: "POST", token: session.token }
      );
      setResolution(res.resolution);
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Error");
    } finally {
      setBusy("");
    }
  }

  async function healthcheck() {
    if (!session) return;
    setBusy("hc");
    setError("");
    try {
      await platformApi("/api/v1/platform/regions/healthcheck", { method: "POST", token: session.token });
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Error");
    } finally {
      setBusy("");
    }
  }

  return (
    <div className="space-y-6">
      <PageHeader title="Multi-Region & Edge" subtitle="Réplicas por región, failover con healthchecks y edge cache de respuestas." />
      {error && <ErrorInline>{error}</ErrorInline>}
      {loading ? (
        <SkeletonBlock className="h-40" />
      ) : (
        <>
          <div className="grid grid-cols-1 gap-6 lg:grid-cols-3">
            <div className="lg:col-span-2">
              <h3 className="mb-2 text-sm font-semibold text-text">Regiones y réplicas</h3>
              <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
                {regions.map((r) => {
                  const rep = r.replicas[0];
                  const healthy = rep?.healthy ?? true;
                  return (
                    <div key={r.id} className={`panel p-4 ${!healthy ? "border-danger" : ""}`}>
                      <div className="flex items-center justify-between">
                        <p className="mono text-sm font-semibold text-text">{r.code}</p>
                        <span className={`badge ${healthy ? "badge-ok" : "badge-danger"}`}>
                          {healthy ? "healthy" : "down"}
                        </span>
                      </div>
                      <p className="text-xs text-faint">{r.name}</p>
                      {rep && (
                        <p className="mt-1 text-[11px] text-faint">
                          {rep.kind} · {rep.endpoint} · {rep.last_latency_ms != null ? `${rep.last_latency_ms.toFixed(0)}ms` : "sin probe"} ·{" "}
                          {rep.last_health_at ? new Date(rep.last_health_at).toLocaleTimeString() : "—"}
                        </p>
                      )}
                      <button
                        type="button"
                        className="btn btn-secondary mt-2 min-h-8 px-2 text-xs"
                        disabled={!!busy || !selectedOrg}
                        onClick={() => void failover(r.code)}
                      >
                        Simular failover
                      </button>
                    </div>
                  );
                })}
              </div>
              <div className="mt-3 flex items-center gap-2">
                <select className="rounded-md border border-border bg-soft px-2 py-2 text-sm" value={selectedOrg} onChange={(e) => setSelectedOrg(e.target.value)}>
                  <option value="">Org para failover…</option>
                  {orgs.map((o) => (<option key={o.id} value={o.id}>{o.id.slice(0, 8)}</option>))}
                </select>
                <button type="button" className="btn btn-primary min-h-9 text-xs" disabled={!!busy || !selectedOrg} onClick={() => void resolve(selectedOrg)}>
                  Resolver región
                </button>
                <button type="button" className="btn btn-secondary min-h-9 text-xs" disabled={!!busy} onClick={() => void healthcheck()}>
                  Healthcheck ahora
                </button>
              </div>
              {resolution && (
                <pre className="mt-2 max-h-40 overflow-auto whitespace-pre-wrap rounded-md bg-soft p-3 text-[11px] text-text">
                  {JSON.stringify(resolution, null, 2)}
                </pre>
              )}
            </div>

            <div className="space-y-3">
              <section className="panel p-4">
                <h3 className="mb-2 text-sm font-semibold text-text">Edge cache</h3>
                <p className="stat-label">Hits</p>
                <p className="stat-value">{(cache?.hits ?? 0).toLocaleString()}</p>
                <p className="stat-label mt-2">Misses</p>
                <p className="stat-value">{(cache?.misses ?? 0).toLocaleString()}</p>
                <p className="mt-2 text-xs text-faint">
                  Hit ratio: <span className="text-text">{(cache?.hit_ratio ?? 0) * 100}%</span>
                </p>
              </section>
              <section className="panel p-4">
                <h3 className="mb-2 flex items-center gap-2 text-sm font-semibold text-text">
                  <Warning size={14} aria-hidden /> Latencia por región
                </h3>
                {latency.length === 0 && <p className="text-xs text-faint">Sin tráfico en 24h.</p>}
                {latency.map((l) => (
                  <div key={l.region} className="mb-1 flex items-center justify-between rounded-md bg-soft px-3 py-1.5 text-xs">
                    <span className="mono text-text">{l.region}</span>
                    <span className="text-faint">{l.requests} req</span>
                    <span className="text-faint">p95 {l.p95_latency_ms.toFixed(0)}ms</span>
                  </div>
                ))}
              </section>
            </div>
          </div>
        </>
      )}
    </div>
  );
}