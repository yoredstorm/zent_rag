import {
  ArrowRight,
  CalendarBlank,
  ChartLineUp,
  Gauge,
  Heartbeat,
  Lightning,
  ListBullets,
  Stack,
  TrendDown,
  TrendUp,
} from "@phosphor-icons/react";
import { lazy, Suspense, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api";
import { useAuth } from "../auth";
import { EmptyState, ErrorInline, PageHeader, SkeletonBlock, StatCard } from "../components/ui";
import { fmtDateTime, fmtLatency, fmtNum, timeAgo } from "../lib/format";

function dayGreeting(company?: string): string {
  const hour = new Date().getHours();
  const hello =
    hour < 12 ? "Buenos días" : hour < 19 ? "Buenas tardes" : "Buenas noches";
  if (company) return `${hello}, ${company}.`;
  return `${hello}.`;
}

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

export default function DashboardPage() {
  const { session } = useAuth();
  const [sub, setSub] = useState<Subscription | null>(null);
  const [usage, setUsage] = useState<Usage | null>(null);
  const [health, setHealth] = useState<"ok" | "down">("ok");
  const [lazyActivity, setLazyActivity] = useState<LazyActivity | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  useEffect(() => {
    if (!session) return;
    (async () => {
      setLoading(true);
      setError("");
      try {
        const h = await fetch("/health");
        setHealth(h.ok ? "ok" : "down");
        const [subData, usageData, lazyData] = await Promise.all([
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
        ]);
        setSub(subData);
        setUsage(usageData);
        setLazyActivity(lazyData);
      } catch (err) {
        setError(err instanceof Error ? err.message : "Error cargando dashboard");
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

  return (
    <div>
      <PageHeader
        title={dayGreeting(session?.companyName)}
        subtitle="Estado de tu plan, cuota y salud del asistente."
      />

      <ErrorInline message={error} />

      {loading ? (
        <div className="grid grid-cols-2 gap-3 md:grid-cols-3 xl:grid-cols-5">
          {Array.from({ length: 5 }).map((_, i) => (
            <div key={i} className="stat space-y-2">
              <SkeletonBlock rows={1} />
            </div>
          ))}
        </div>
      ) : (
        <>
          <div className="grid grid-cols-2 gap-3 md:grid-cols-3 xl:grid-cols-5">
            <StatCard
              label="Plan"
              value={sub?.plan_name || sub?.status || "—"}
              icon={Stack}
            />
            <StatCard
              label="Cuota del mes"
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
              label="Estado del servicio"
              value={health === "ok" ? "Operativo" : "Degradado"}
              icon={Heartbeat}
              tone={health === "ok" ? "ok" : "danger"}
              hint="API, base de datos y buscador"
            />
            <StatCard
              label="Trial hasta"
              value={
                sub?.trial_end ? new Date(sub.trial_end).toLocaleDateString() : "—"
              }
              icon={CalendarBlank}
            />
            <StatCard
              label="Consultas IA"
              value={fmtNum(usage?.totals.requests ?? 0)}
              icon={Lightning}
            />
            <StatCard
              label="Tokens"
              value={fmtNum(usage?.totals.tokens ?? 0)}
              icon={ChartLineUp}
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
                    body="Cuando hagas preguntas al asistente, verás aquí la actividad diaria."
                    action={
                      <Link to="/chat" className="btn btn-secondary">
                        Hacer una pregunta <ArrowRight size={15} aria-hidden />
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
                <h2 className="text-sm font-semibold text-text">Consultas recientes</h2>
                <Link
                  to="/usage"
                  className="flex items-center gap-1 text-xs text-accent hover:underline"
                >
                  Ver uso <ArrowRight size={12} aria-hidden />
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
                            <span className="mono">
                              {ev.rows_indexed} filas
                            </span>
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
                <h2 className="text-sm font-semibold text-text">Siguiente paso</h2>
              </div>
              <div className="flex flex-col gap-2 p-4">
                <Link
                  to="/knowledge/sql"
                  className="group flex items-center justify-between rounded-md border border-border bg-soft px-4 py-3 text-sm text-text transition-all duration-200 hover:border-accent/40 hover:bg-raised"
                >
                  Sincronizar datos
                  <ArrowRight size={15} className="text-faint transition-transform group-hover:translate-x-0.5" aria-hidden />
                </Link>
                <Link
                  to="/chat"
                  className="group flex items-center justify-between rounded-md border border-border bg-soft px-4 py-3 text-sm text-text transition-all duration-200 hover:border-accent/40 hover:bg-raised"
                >
                  Hacer una pregunta
                  <ArrowRight size={15} className="text-faint transition-transform group-hover:translate-x-0.5" aria-hidden />
                </Link>
                <Link
                  to="/keys"
                  className="group flex items-center justify-between rounded-md border border-border bg-soft px-4 py-3 text-sm text-text transition-all duration-200 hover:border-accent/40 hover:bg-raised"
                >
                  Ver clave de integración
                  <ArrowRight size={15} className="text-faint transition-transform group-hover:translate-x-0.5" aria-hidden />
                </Link>
                <Link
                  to="/prompts"
                  className="group flex items-center justify-between rounded-md border border-border bg-soft px-4 py-3 text-sm text-text transition-all duration-200 hover:border-accent/40 hover:bg-raised"
                >
                  Ajustar prompts
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
        </>
      )}
    </div>
  );
}
