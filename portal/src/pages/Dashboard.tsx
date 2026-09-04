import {
  ArrowRight,
  CalendarBlank,
  ChartLineUp,
  Gauge,
  Heartbeat,
  Lightning,
  ListBullets,
  Robot,
  Stack,
  Star,
  TrendDown,
  TrendUp,
  WarningCircle,
} from "@phosphor-icons/react";
import { lazy, Suspense, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api";
import { useAuth } from "../auth";
import { EmptyState, ErrorInline, PageHeader, SkeletonBlock, StatCard } from "../components/ui";
import { fmtDateTime, fmtLatency, fmtNum, timeAgo } from "../lib/format";

const UsageChart = lazy(() => import("../components/UsageChart"));

type Subscription = {
  plan_name: string | null;
  status: string;
  requests_used: number;
  requests_limit: number | null;
  trial_end: string | null;
};

type Usage = {
  totals: {
    requests: number;
    tokens: number;
    avg_latency_ms: number;
    errors?: number;
    estimated_cost?: number;
  };
  daily: { day: string; requests: number; tokens: number; avg_latency_ms: number }[];
  recent: {
    id: number;
    total_tokens: number;
    latency_ms: number;
    model: string | null;
    created_at: string;
  }[];
};

type LazyEvent = {
  tables: string[];
  rows_indexed: number;
  query_preview: string;
  at: string;
};

type LazyActivity = {
  trigger_count: number;
  total_rows_indexed?: number;
  rate_limited?: boolean;
  recent: LazyEvent[];
};

type EvalStats = {
  total_evaluations: number;
  approval_rate: number;
};

type HealthChecks = Record<string, string>;

const SERVICE_LABELS: Record<string, string> = {
  api: "API",
  postgres: "Base de datos",
  qdrant: "Vector DB",
  redis: "Redis",
};

export default function DashboardPage() {
  const { session } = useAuth();
  const [sub, setSub] = useState<Subscription | null>(null);
  const [usage, setUsage] = useState<Usage | null>(null);
  const [health, setHealth] = useState<"ok" | "down">("ok");
  const [checks, setChecks] = useState<HealthChecks>({});
  const [agentCount, setAgentCount] = useState<number | null>(null);
  const [quality, setQuality] = useState<EvalStats | null>(null);
  const [lazyActivity, setLazyActivity] = useState<LazyActivity | null>(null);
  const [issues, setIssues] = useState<{ id: string; label: string; to: string }[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  useEffect(() => {
    if (!session) return;
    (async () => {
      setLoading(true);
      setError("");
      try {
        const h = await fetch("/health");
        const healthData = await h.json().catch(() => ({ checks: {} as HealthChecks }));
        setHealth(h.ok && healthData.status === "healthy" ? "ok" : "down");
        setChecks(healthData.checks || {});
        const [subData, usageData, lazyData, agentData, qualityData, sourceData] =
          await Promise.all([
            api<Subscription>("/api/v1/billing/subscription", {
              token: session.token,
              organizationId: session.organizationId,
            }),
            api<Usage>("/api/v1/billing/usage?days=30", {
              token: session.token,
              organizationId: session.organizationId,
            }),
            api<LazyActivity>("/api/v1/ingestion/lazy-activity?days=30", {
              token: session.token,
              organizationId: session.organizationId,
            }).catch(() => ({ trigger_count: 0, recent: [] as LazyEvent[] })),
            api<{ agents: unknown[] }>("/api/v1/agents", {
              token: session.token,
              organizationId: session.organizationId,
            }).catch(() => ({ agents: [] as unknown[] })),
            api<EvalStats>("/api/v1/eval/stats?days=30", {
              token: session.token,
              organizationId: session.organizationId,
            }).catch(() => null),
            api<{ sources: { id: string; name: string; status: string }[] }>(
              "/api/v1/sources",
              {
                token: session.token,
                organizationId: session.organizationId,
              }
            ).catch(() => ({ sources: [] as { id: string; name: string; status: string }[] })),
          ]);
        setSub(subData);
        setUsage(usageData);
        setLazyActivity(lazyData);
        setAgentCount((agentData.agents || []).length);
        setQuality(qualityData);
        const bad = (sourceData.sources || []).filter(
          (s) => s.status === "error" || s.status === "failed"
        );
        setIssues(
          bad.slice(0, 5).map((s) => ({
            id: s.id,
            label: `La fuente «${s.name}» no se sincronizó correctamente.`,
            to: "/knowledge/sources",
          }))
        );
      } catch (err) {
        setError(err instanceof Error ? err.message : "Error cargando panel");
      } finally {
        setLoading(false);
      }
    })();
  }, [session]);

  const limit = sub?.requests_limit ?? null;
  const used = sub?.requests_used ?? 0;
  const quotaPct =
    limit && limit > 0 ? Math.min(100, Math.round((used / limit) * 100)) : null;
  const daily = usage?.daily ?? [];
  const recentQueries = usage?.recent ?? [];
  const lazyEvents = (lazyActivity?.recent ?? []).slice(0, 5);
  const services = ["api", "postgres", "qdrant", "redis"] as const;

  return (
    <div>
      <PageHeader
        title="Panel general"
        subtitle="Monitorea tu workspace de IA, el uso y la salud de la plataforma."
      />

      <ErrorInline message={error} />

      {loading ? (
        <div className="grid grid-cols-2 gap-3 md:grid-cols-3 xl:grid-cols-6">
          {Array.from({ length: 6 }).map((_, i) => (
            <div key={i} className="stat space-y-2">
              <SkeletonBlock rows={1} />
            </div>
          ))}
        </div>
      ) : (
        <>
          <div className="grid grid-cols-2 gap-3 md:grid-cols-3 xl:grid-cols-6">
            <StatCard
              label="Solicitudes"
              value={fmtNum(usage?.totals.requests ?? 0)}
              icon={Lightning}
            />
            <StatCard
              label="Uso del período"
              value={limit ? `${fmtNum(used)} / ${fmtNum(limit)}` : fmtNum(used)}
              icon={Gauge}
              hint={
                quotaPct !== null && (
                  <span className="mt-2 block">
                    <span className="progress-track">
                      <span
                        className={`progress-fill ${quotaPct >= 85 ? "bg-danger" : quotaPct >= 60 ? "bg-warn" : ""}`}
                        style={{ width: `${quotaPct}%` }}
                      />
                    </span>
                    <span className="mono mt-1 inline-block text-[11px] text-faint">
                      {quotaPct}% usado
                    </span>
                  </span>
                )
              }
            />
            <StatCard
              label="Plan"
              value={sub?.plan_name || sub?.status || "—"}
              icon={Stack}
            />
            <StatCard
              label="Estado del sistema"
              value={health === "ok" ? "Operativo" : "Degradado"}
              icon={Heartbeat}
              tone={health === "ok" ? "ok" : "danger"}
            />
            <StatCard
              label="Agentes activos"
              value={agentCount != null ? fmtNum(agentCount) : "—"}
              icon={Robot}
            />
            <StatCard
              label="Calidad de IA"
              value={quality?.total_evaluations ? `${quality.approval_rate}%` : "—"}
              icon={Star}
              tone={
                quality && quality.approval_rate >= 70 ? "ok" : "default"
              }
              hint={quality?.total_evaluations ? `${fmtNum(quality.total_evaluations)} evaluaciones` : "sin feedback aún"}
            />
          </div>

          <div className="mt-4 grid gap-4 xl:grid-cols-3">
            <div className="panel xl:col-span-2">
              <div className="flex items-center justify-between border-b border-border px-5 py-4">
                <h2 className="text-sm font-semibold text-text">Consultas por día</h2>
                <span className="mono text-[11px] text-faint">últimos 30 días</span>
              </div>
              <div className="p-4">
                {daily.length === 0 ? (
                  <EmptyState
                    icon={ChartLineUp}
                    title="Aún no hay consultas"
                    body="Cuando hagas preguntas en el Playground, verás aquí la actividad diaria."
                    action={
                      <Link to="/chat" className="btn btn-secondary">
                        Probar el Playground <ArrowRight size={15} aria-hidden />
                      </Link>
                    }
                  />
                ) : (
                  <Suspense
                    fallback={
                      <div className="flex h-[240px] items-center justify-center">
                        <span
                          className="inline-block h-5 w-5 animate-spin rounded-full border-2 border-border-strong border-t-accent"
                          aria-label="Cargando gráfico"
                        />
                      </div>
                    }
                  >
                    <UsageChart daily={daily} />
                  </Suspense>
                )}
              </div>
            </div>

            <div className="panel">
              <div className="flex items-center justify-between border-b border-border px-5 py-4">
                <h2 className="text-sm font-semibold text-text">Estado de la plataforma</h2>
                <Link
                  to="/deployments"
                  className="flex items-center gap-1 text-xs text-accent hover:underline"
                >
                  Despliegues <ArrowRight size={12} aria-hidden />
                </Link>
              </div>
              <ul className="divide-y divide-border/60 px-2">
                {services.map((service) => {
                  const value = checks[service];
                  const healthy = value === "ok";
                  return (
                    <li
                      key={service}
                      className="flex items-center justify-between gap-2 px-3 py-2.5"
                    >
                      <span className="text-[13px] text-text">{SERVICE_LABELS[service]}</span>
                      {value ? (
                        <span
                          className={`badge ${healthy ? "badge-ok" : "badge-danger"}`}
                        >
                          <span className="status-dot mr-1 bg-current" aria-hidden />
                          {healthy ? "Saludable" : "Degradado"}
                        </span>
                      ) : (
                        <span className="badge badge-muted">No verificado</span>
                      )}
                    </li>
                  );
                })}
              </ul>
            </div>
          </div>

          <div className="mt-4 grid gap-4 xl:grid-cols-3">
            <div className="panel xl:col-span-2">
              <div className="flex items-center justify-between border-b border-border px-5 py-4">
                <h2 className="text-sm font-semibold text-text">Necesita atención</h2>
                <span className="mono text-[11px] text-faint">eventos reales</span>
              </div>
              {issues.length === 0 ? (
                <div className="flex flex-col items-center gap-2 px-6 py-10 text-center">
                  <span className="flex h-11 w-11 items-center justify-center rounded-md border border-border bg-soft text-ok">
                    <Heartbeat size={22} aria-hidden />
                  </span>
                  <p className="mt-1 text-sm font-medium text-text">Todo en orden</p>
                  <p className="max-w-sm text-[13px] leading-relaxed text-muted">
                    No se detectaron problemas en tu workspace.
                  </p>
                </div>
              ) : (
                <ul className="divide-y divide-border/60 px-2">
                  {issues.map((issue) => (
                    <li key={issue.id} className="flex items-center justify-between gap-3 px-3 py-3">
                      <span className="flex items-center gap-2 text-[13px] text-text">
                        <WarningCircle size={15} className="shrink-0 text-warn" aria-hidden />
                        {issue.label}
                      </span>
                      <Link to={issue.to} className="shrink-0 text-xs text-accent hover:underline">
                        Revisar
                      </Link>
                    </li>
                  ))}
                </ul>
              )}
            </div>

            <div className="panel">
              <div className="flex items-center justify-between border-b border-border px-5 py-4">
                <h2 className="text-sm font-semibold text-text">Consultas recientes</h2>
                <Link
                  to="/usage"
                  className="flex items-center gap-1 text-xs text-accent hover:underline"
                >
                  Analítica <ArrowRight size={12} aria-hidden />
                </Link>
              </div>
              {recentQueries.length === 0 ? (
                <EmptyState
                  icon={ListBullets}
                  title="Sin consultas recientes"
                  body="Tus últimas preguntas y su rendimiento aparecerán aquí."
                />
              ) : (
                <ul className="divide-y divide-border/60 px-2">
                  {recentQueries.slice(0, 6).map((r) => (
                    <li key={r.id} className="flex items-center justify-between gap-3 px-3 py-2.5">
                      <div className="min-w-0">
                        <p className="mono truncate text-xs text-muted">
                          {r.model || "modelo por defecto"}
                        </p>
                        <p className="text-[11px] text-faint">{fmtDateTime(r.created_at)}</p>
                      </div>
                      <div className="flex shrink-0 flex-col items-end">
                        <span className="mono text-[11px] text-text">
                          {fmtLatency(r.latency_ms)}
                        </span>
                        <span className="mono text-[11px] text-faint">
                          {fmtNum(r.total_tokens)} tok
                        </span>
                      </div>
                    </li>
                  ))}
                </ul>
              )}
            </div>
          </div>

          <div className="mt-4 grid gap-4 xl:grid-cols-3">
            <div className="panel xl:col-span-2">
              <div className="flex items-center justify-between border-b border-border px-5 py-4">
                <h2 className="text-sm font-semibold text-text">Indexado por demanda</h2>
                <span className="mono text-[11px] text-faint">últimos 30 días</span>
              </div>
              {lazyEvents.length === 0 ? (
                <EmptyState
                  icon={Lightning}
                  title="Sin indexados automáticos"
                  body="Cuando una pregunta necesite datos aún no sincronizados, el sistema los indexará y quedará registrado aquí."
                />
              ) : (
                <ul className="divide-y divide-border/60 px-2">
                  {lazyEvents.map((ev, i) => (
                    <li key={`${ev.at}-${i}`} className="px-3 py-3">
                      <div className="flex flex-wrap items-center justify-between gap-2">
                        <span className="mono text-xs text-accent">
                          {(ev.tables || []).join(", ") || "—"}
                        </span>
                        <span className="flex items-center gap-2 text-[11px] text-faint">
                          {ev.rows_indexed > 0 && (
                            <span className="mono">{ev.rows_indexed} filas</span>
                          )}
                          · {timeAgo(ev.at)}
                        </span>
                      </div>
                      {ev.query_preview && (
                        <p className="mt-1 truncate text-[13px] text-muted" title={ev.query_preview}>
                          «{ev.query_preview}»
                        </p>
                      )}
                    </li>
                  ))}
                </ul>
              )}
            </div>

            <div className="panel">
              <div className="border-b border-border px-5 py-4">
                <h2 className="text-sm font-semibold text-text">Próximos pasos</h2>
              </div>
              <div className="flex flex-col gap-2 p-4">
                <Link
                  to="/knowledge/sql"
                  className="group flex items-center justify-between rounded-md border border-border bg-soft px-4 py-3 text-sm text-text transition-all duration-200 hover:border-accent/40 hover:bg-raised"
                >
                  Conectar conocimiento
                  <ArrowRight size={15} className="text-faint transition-transform group-hover:translate-x-0.5" aria-hidden />
                </Link>
                <Link
                  to="/chat"
                  className="group flex items-center justify-between rounded-md border border-border bg-soft px-4 py-3 text-sm text-text transition-all duration-200 hover:border-accent/40 hover:bg-raised"
                >
                  Probar el Playground
                  <ArrowRight size={15} className="text-faint transition-transform group-hover:translate-x-0.5" aria-hidden />
                </Link>
                <Link
                  to="/agents"
                  className="group flex items-center justify-between rounded-md border border-border bg-soft px-4 py-3 text-sm text-text transition-all duration-200 hover:border-accent/40 hover:bg-raised"
                >
                  Crear un agente
                  <ArrowRight size={15} className="text-faint transition-transform group-hover:translate-x-0.5" aria-hidden />
                </Link>
                <Link
                  to="/keys"
                  className="group flex items-center justify-between rounded-md border border-border bg-soft px-4 py-3 text-sm text-text transition-all duration-200 hover:border-accent/40 hover:bg-raised"
                >
                  Ver credenciales de API
                  <ArrowRight size={15} className="text-faint transition-transform group-hover:translate-x-0.5" aria-hidden />
                </Link>
              </div>
            </div>
          </div>

          {(usage?.totals.requests ?? 0) > 0 && (
            <p className="mt-4 flex items-center gap-1.5 text-xs text-faint">
              {usage!.totals.requests > 10 ? (
                <TrendUp size={14} className="text-ok" aria-hidden />
              ) : (
                <TrendDown size={14} className="text-muted" aria-hidden />
              )}
              <span className="mono">{fmtNum(usage!.totals.requests)}</span> consultas,{" "}
              <span className="mono">{fmtNum(usage!.totals.tokens)}</span> tokens,{" "}
              <span className="mono">{fmtLatency(usage!.totals.avg_latency_ms)}</span> de latencia
              media en los últimos 30 días.
            </p>
          )}

          {sub?.trial_end && (
            <p className="mt-2 flex items-center gap-1.5 text-xs text-faint">
              <CalendarBlank size={14} aria-hidden />
              Trial hasta {new Date(sub.trial_end).toLocaleDateString()}
            </p>
          )}
        </>
      )}
    </div>
  );
}