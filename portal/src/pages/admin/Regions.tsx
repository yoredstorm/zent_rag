import { Gauge, Pulse } from "@phosphor-icons/react";
import { useEffect, useState } from "react";
import { platformApi } from "../../api";
import {
  Badge,
  Button,
  CodeBlock,
  ConfirmDialog,
  Drawer,
  EmptyState,
  ErrorInline,
  Field,
  KeyValue,
  Metric,
  MetricGrid,
  PageHeader,
  Panel,
  PanelHeader,
  Progress,
  SectionHeader,
  Select,
  SkeletonTable,
  StatusBadge,
  Toolbar,
} from "../../components/ui";
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

/** El vocabulario del backend usa ok/down además de healthy/degraded. */
function normalizeStatus(status: string): string {
  if (status === "ok") return "healthy";
  if (status === "down") return "failed";
  return status;
}

function formatDateTime(value: string | null) {
  return value ? new Date(value).toLocaleString("es-PE") : "—";
}

export default function AdminRegionsPage() {
  const { session } = usePlatformAuth();
  const [regions, setRegions] = useState<Region[]>([]);
  const [latency, setLatency] = useState<RegionLatency[]>([]);
  const [cache, setCache] = useState<{ hits: number; misses: number; total: number; hit_ratio: number } | null>(null);
  const [orgs, setOrgs] = useState<{ id: string }[]>([]);
  const [selectedOrg, setSelectedOrg] = useState("");
  const [resolution, setResolution] = useState<Record<string, unknown> | null>(null);
  const [detailRegion, setDetailRegion] = useState<Region | null>(null);
  const [confirmFailover, setConfirmFailover] = useState<Region | null>(null);
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
      setConfirmFailover(null);
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

  const replicas = regions.flatMap((r) => r.replicas ?? []);
  const downReplicas = replicas.filter((r) => !r.healthy);
  const healthyReplicas = replicas.length - downReplicas.length;
  const healthyPct = replicas.length ? (healthyReplicas / replicas.length) * 100 : 0;
  const downCodes = regions
    .filter((r) => (r.replicas ?? []).some((rep) => !rep.healthy))
    .map((r) => r.code)
    .join(", ");
  const maxP95 = Math.max(...latency.map((l) => l.p95_latency_ms), 0.001);

  return (
    <div className="space-y-6">
      <PageHeader
        title="Multi-Region & Edge"
        subtitle="Réplicas por región, failover con healthchecks y edge cache de respuestas."
      />
      <ErrorInline message={error} />
      {loading ? (
        <Panel className="overflow-hidden">
          <SkeletonTable rows={6} cols={5} />
        </Panel>
      ) : (
        <>
          <Panel className={`p-4 ${downReplicas.length > 0 ? "border-danger/40" : ""}`}>
            <div className="flex flex-wrap items-start justify-between gap-x-8 gap-y-4">
              <div className="min-w-0">
                <p className="eyebrow">Réplicas saludables</p>
                <p className="mt-2 text-[30px] leading-none font-semibold tracking-[-0.025em] tabular-nums text-text">
                  {regions.length === 0 ? "—" : `${healthyReplicas}/${replicas.length}`}
                </p>
                <p className="mt-2 max-w-[68ch] text-[13px] leading-relaxed text-muted">
                  {regions.length === 0
                    ? "No hay regiones registradas en la plataforma."
                    : downReplicas.length > 0
                      ? `${downReplicas.length} réplica(s) sin healthcheck en ${downCodes}. Simulá el failover para verificar el recálculo de región.`
                      : "Todas las réplicas responden el healthcheck del backend."}
                </p>
              </div>
              <div className="min-w-[220px] flex-1 sm:max-w-sm">
                {replicas.length > 0 ? (
                  <Progress
                    value={healthyPct}
                    tone={downReplicas.length > 0 ? "danger" : "ok"}
                    label="Réplicas sanas"
                    showValue
                  />
                ) : (
                  <p className="text-xs text-faint">Sin réplicas para medir.</p>
                )}
              </div>
            </div>
          </Panel>

          <MetricGrid cols={4}>
            <Metric size="md" label="Regiones" value={regions.length.toLocaleString()} />
            <Metric
              size="md"
              label="Réplicas"
              value={replicas.length.toLocaleString()}
              hint={`${healthyReplicas} sanas`}
            />
            <Metric
              size="md"
              label="Réplicas caídas"
              value={downReplicas.length.toLocaleString()}
              tone={downReplicas.length > 0 ? "danger" : "default"}
            />
            <Metric
              size="md"
              label="Edge hit ratio"
              value={cache ? `${(cache.hit_ratio * 100).toFixed(1)}%` : "—"}
              hint={cache ? `${cache.total.toLocaleString()} respuestas medidas` : "Sin estadísticas"}
            />
          </MetricGrid>

          <div className="grid grid-cols-1 gap-6 lg:grid-cols-3">
            <section className="lg:col-span-2">
              <SectionHeader
                title="Regiones y réplicas"
                description="Estado, prioridad y probe de cada región. El failover se simula contra la organización elegida."
                className="mb-3"
              />
              <Toolbar className="mb-3">
                <Field label="Organización para failover" className="w-full sm:w-56">
                  <Select
                    value={selectedOrg}
                    placeholder="Organización…"
                    onChange={(e) => setSelectedOrg(e.target.value)}
                  >
                    {orgs.map((o) => (
                      <option key={o.id} value={o.id}>
                        {o.id.slice(0, 8)}
                      </option>
                    ))}
                  </Select>
                </Field>
                <Button
                  variant="secondary"
                  disabled={!selectedOrg || !!busy}
                  onClick={() => void resolve(selectedOrg)}
                >
                  Resolver región
                </Button>
                <Button
                  variant="secondary"
                  leadingIcon={Pulse}
                  loading={busy === "hc"}
                  onClick={() => void healthcheck()}
                >
                  Healthcheck ahora
                </Button>
              </Toolbar>
              <Panel className="overflow-x-auto">
                {regions.length === 0 ? (
                  <EmptyState
                    icon={Gauge}
                    compact
                    title="Sin regiones"
                    body="El backend no devolvió regiones configuradas."
                  />
                ) : (
                  <table className="table min-w-[960px]">
                    <thead>
                      <tr>
                        <th>Región</th>
                        <th>Nombre</th>
                        <th>Estado</th>
                        <th className="text-right">Prioridad</th>
                        <th>Réplicas</th>
                        <th className="text-right">Probe</th>
                        <th>Último health</th>
                        <th className="text-right">Acciones</th>
                      </tr>
                    </thead>
                    <tbody>
                      {regions.map((r) => {
                        const reps = r.replicas ?? [];
                        const down = reps.filter((rep) => !rep.healthy).length;
                        const probe = reps[0];
                        return (
                          <tr key={r.id}>
                            <td className="mono font-medium">{r.code}</td>
                            <td className="text-muted">{r.name}</td>
                            <td>
                              <StatusBadge status={normalizeStatus(r.status)} />
                            </td>
                            <td className="text-right tabular-nums">{r.priority}</td>
                            <td className={down > 0 ? "text-danger" : "text-muted"}>
                              <span className="tabular-nums">
                                {reps.length - down}/{reps.length}
                              </span>{" "}
                              sanas
                            </td>
                            <td className="text-right tabular-nums">
                              {probe?.last_latency_ms != null ? `${probe.last_latency_ms.toFixed(0)}ms` : "—"}
                            </td>
                            <td className="text-xs text-muted tabular-nums">
                              {formatDateTime(probe?.last_health_at ?? null)}
                            </td>
                            <td className="text-right whitespace-nowrap">
                              <Button size="sm" variant="ghost" onClick={() => setDetailRegion(r)}>
                                Detalle
                              </Button>
                              <Button
                                size="sm"
                                variant="secondary"
                                disabled={!selectedOrg || !!busy}
                                onClick={() => setConfirmFailover(r)}
                              >
                                Simular failover
                              </Button>
                            </td>
                          </tr>
                        );
                      })}
                    </tbody>
                  </table>
                )}
              </Panel>
              {resolution && (
                <CodeBlock
                  className="mt-3"
                  code={JSON.stringify(resolution, null, 2)}
                  language="json"
                  filename="Resolución de región"
                  maxHeight={280}
                />
              )}
            </section>

            <div className="space-y-4">
              <Panel>
                <PanelHeader
                  title="Edge cache"
                  description="Respuestas servidas desde el borde en esta instancia."
                />
                <div className="space-y-3 p-4">
                  <Progress
                    value={(cache?.hit_ratio ?? 0) * 100}
                    label="Hit ratio"
                    showValue
                  />
                  <dl className="grid grid-cols-2 gap-3">
                    <div>
                      <dt className="eyebrow">Hits</dt>
                      <dd className="mt-1 text-sm tabular-nums text-text">
                        {(cache?.hits ?? 0).toLocaleString()}
                      </dd>
                    </div>
                    <div>
                      <dt className="eyebrow">Misses</dt>
                      <dd className="mt-1 text-sm tabular-nums text-text">
                        {(cache?.misses ?? 0).toLocaleString()}
                      </dd>
                    </div>
                  </dl>
                </div>
              </Panel>

              <Panel>
                <PanelHeader
                  title="Latencia por región"
                  description="Tráfico de las últimas 24 horas."
                />
                {latency.length === 0 ? (
                  <EmptyState
                    icon={Gauge}
                    compact
                    title="Sin tráfico en 24h"
                    body="Ninguna región registró requests en la ventana consultada."
                  />
                ) : (
                  <ul className="divide-y divide-border-soft">
                    {latency.map((l) => (
                      <li key={l.region} className="px-4 py-3">
                        <div className="flex items-center justify-between gap-3 text-xs">
                          <span className="mono text-text">{l.region}</span>
                          <span className="text-faint tabular-nums">{l.requests.toLocaleString()} req</span>
                        </div>
                        <span className="mt-1.5 flex items-center gap-2">
                          <span className="h-1.5 flex-1 overflow-hidden rounded-full bg-track" aria-hidden>
                            <span
                              className="block h-full rounded-full bg-accent"
                              style={{ width: `${(l.p95_latency_ms / maxP95) * 100}%` }}
                            />
                          </span>
                          <span className="w-20 text-right text-xs text-faint tabular-nums">
                            p95 {l.p95_latency_ms.toFixed(0)}ms
                          </span>
                        </span>
                        <p className="mt-1 text-[11px] text-faint tabular-nums">
                          promedio {l.avg_latency_ms.toFixed(0)}ms
                        </p>
                      </li>
                    ))}
                  </ul>
                )}
              </Panel>
            </div>
          </div>
        </>
      )}

      <Drawer
        open={detailRegion !== null}
        onOpenChange={(open) => !open && setDetailRegion(null)}
        title={detailRegion ? `Región ${detailRegion.code}` : "Región"}
        description={detailRegion?.name}
      >
        {detailRegion && (
          <div className="space-y-5">
            <div className="flex flex-wrap items-center gap-2">
              <StatusBadge status={normalizeStatus(detailRegion.status)} />
              <Badge tone="neutral">Prioridad {detailRegion.priority}</Badge>
              <Badge tone="neutral">{detailRegion.replicas.length} réplica(s)</Badge>
            </div>
            <KeyValue
              columns={2}
              items={[
                { key: "ID", value: detailRegion.id, mono: true },
                { key: "Código", value: detailRegion.code, mono: true },
                { key: "Nombre", value: detailRegion.name },
                { key: "Estado", value: normalizeStatus(detailRegion.status) },
              ]}
            />
            <div>
              <h3 className="eyebrow mb-2">Réplicas</h3>
              {detailRegion.replicas.length === 0 ? (
                <p className="text-[13px] text-muted">La región no tiene réplicas registradas.</p>
              ) : (
                <ul className="divide-y divide-border-soft rounded-md border border-border">
                  {detailRegion.replicas.map((rep) => (
                    <li
                      key={rep.id}
                      className="flex flex-wrap items-center justify-between gap-2 px-3 py-2.5"
                    >
                      <div className="min-w-0">
                        <p className="mono truncate text-xs text-text" title={rep.endpoint}>
                          {rep.endpoint}
                        </p>
                        <p className="text-[11px] text-faint">
                          {rep.kind} ·{" "}
                          {rep.last_latency_ms != null ? `${rep.last_latency_ms.toFixed(0)}ms` : "sin probe"}{" "}
                          · {formatDateTime(rep.last_health_at)}
                        </p>
                      </div>
                      <StatusBadge status={rep.healthy ? "healthy" : "failed"} />
                    </li>
                  ))}
                </ul>
              )}
            </div>
          </div>
        )}
      </Drawer>

      <ConfirmDialog
        open={confirmFailover !== null}
        onOpenChange={(open) => !open && setConfirmFailover(null)}
        title="Simular failover"
        body={
          confirmFailover
            ? `El backend marca ${confirmFailover.code} como no saludable y recalcula la resolución para la organización elegida. Es una simulación: no cambia el tráfico real.`
            : undefined
        }
        confirmLabel="Simular"
        tone="primary"
        loading={confirmFailover !== null && busy === confirmFailover.code}
        onConfirm={() => confirmFailover && void failover(confirmFailover.code)}
      />
    </div>
  );
}
