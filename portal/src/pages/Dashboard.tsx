import {
  ArrowRight,
  CalendarBlank,
  ChartLineUp,
  Database,
  Heartbeat,
  Lightning,
  ListBullets,
  Plugs,
  Robot,
  Sparkle,
  Star,
  Timer,
} from "@phosphor-icons/react";
import { lazy, Suspense, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api";
import { useAuth } from "../auth";
import { AttentionList } from "../components/AttentionList";
import { KnowledgePillarLinks } from "../components/KnowledgePillarLinks";
import {
  EmptyState,
  ErrorInline,
  Progress,
  Skeleton,
  WarningInline,
} from "../components/ui";
import { ButtonLink } from "../components/ui/Button";
import { Metric, MetricGrid, PageHeader, Panel, PanelHeader } from "../components/ui/surface";
import { StatusDot } from "../components/ui/Badge";
import { Tooltip } from "../components/ui/overlay";
import { fmtDateTime, fmtLatency, fmtNum, timeAgo } from "../lib/format";
import { cn } from "../components/ui/cn";

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

const SERVICES = ["api", "postgres", "qdrant", "redis"] as const;

export default function DashboardPage() {
  const { session } = useAuth();
  const [sub, setSub] = useState<Subscription | null>(null);
  const [usage, setUsage] = useState<Usage | null>(null);
  const [health, setHealth] = useState<"ok" | "down">("ok");
  const [checks, setChecks] = useState<HealthChecks>({});
  const [agentCount, setAgentCount] = useState<number | null>(null);
  const [quality, setQuality] = useState<EvalStats | null>(null);
  const [lazyActivity, setLazyActivity] = useState<LazyActivity | null>(null);
  const [hasRealData, setHasRealData] = useState<boolean | null>(null);
  const [resumeId, setResumeId] = useState<string | null>(null);
  const [attentionSessions, setAttentionSessions] = useState<
    Array<{ id: string; warning?: string | null }>
  >([]);
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
        const [subData, usageData, lazyData, agentData, qualityData, sourceData, connData, gateData, attentionData] =
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
            api<{ sources: { id: string; name: string; status: string; type: string }[] }>(
              "/api/v1/sources",
              {
                token: session.token,
                organizationId: session.organizationId,
              }
            ).catch(() => ({ sources: [] as { id: string; name: string; status: string; type: string }[] })),
            api<{ connectors: Array<{ id: string; connector_type: string }> }>(
              "/api/v1/connectors",
              { token: session.token, organizationId: session.organizationId }
            ).catch(() => ({ connectors: [] })),
            api<{ has_real_data: boolean; resume_session_id: string | null }>(
              "/api/v1/data-onboarding/gate",
              { token: session.token, organizationId: session.organizationId }
            ).catch(() => ({ has_real_data: false, resume_session_id: null })),
            api<{ sessions: Array<{ id: string; status: string; warning?: string | null }> }>(
              "/api/v1/data-onboarding/sessions?status=NEEDS_ATTENTION",
              { token: session.token, organizationId: session.organizationId }
            ).catch(() => ({ sessions: [] })),
          ]);
        setSub(subData);
        setUsage(usageData);
        setLazyActivity(lazyData);
        setAgentCount((agentData.agents || []).length);
        setQuality(qualityData);
        const bad = (sourceData.sources || []).filter(
          (s) => s.status === "error" || s.status === "failed"
        );
        const realSources = (sourceData.sources || []).filter((s) => s.type !== "sql");
        const realConnectors = connData.connectors || [];
        setHasRealData(realSources.length > 0 || realConnectors.length > 0);
        setResumeId(gateData.resume_session_id);
        setAttentionSessions(attentionData.sessions || []);
        setIssues(
          bad.slice(0, 5).map((s) => ({
            id: s.id,
            label: `La fuente «${s.name}» no se sincronizó correctamente.`,
            to: "/knowledge/sources",
          }))
        );
      } catch (err) {
        setError(err instanceof Error ? err.message : "No pudimos cargar el panel.");
      } finally {
        setLoading(false);
      }
    })();
  }, [session]);

  const limit = sub?.requests_limit ?? null;
  const used = sub?.requests_used ?? 0;
  const quotaPct = limit && limit > 0 ? Math.min(100, Math.round((used / limit) * 100)) : null;
  const daily = usage?.daily ?? [];
  const recentQueries = usage?.recent ?? [];
  const lazyEvents = (lazyActivity?.recent ?? []).slice(0, 5);
  const outages = SERVICES.filter((s) => checks[s] && checks[s] !== "ok");
  const pending = issues.length + attentionSessions.length;
  const quotaTone = quotaPct === null ? "accent" : quotaPct >= 85 ? "danger" : quotaPct >= 60 ? "warn" : "accent";

  // ------------------------------------------------------------------ //
  // Bienvenida: workspace sin datos reales todavía                      //
  // ------------------------------------------------------------------ //
  if (!loading && hasRealData === false) {
    const steps = [
      {
        title: "Conectá tus fuentes",
        body: "Documentos, bases de datos, APIs o conectores. Zent los interpreta y los deja consultables.",
      },
      {
        title: "Preguntá en el Playground",
        body: "Comprobá respuestas con citas antes de que las use un usuario real.",
      },
      {
        title: "Publicá un agente",
        body: "Elegí conocimiento, herramientas y comportamiento. Después lo servís por chat, API o workflows.",
      },
    ];
    return (
      <div>
        <PageHeader
          title="Panel general"
          subtitle="Cuando conectes datos, acá vas a ver el pulso de tu workspace: salud, consumo y qué pide atención."
        />
        <ErrorInline message={error} />
        <Panel className="p-6 sm:p-8">
          <p className="eyebrow mb-2">Primer paso</p>
          <h2 className="text-display">Bienvenido a Zent</h2>
          <p className="prose-measure mt-2.5 text-sm leading-relaxed text-muted">
            Zent responde con el conocimiento de tu negocio. Empezá conectando una fuente: te guiamos
            paso a paso y podés salir en cualquier momento sin perder lo cargado.
          </p>
          <ol className="mt-7 grid gap-4 sm:grid-cols-3">
            {steps.map((step, i) => (
              <li key={step.title} className="flex gap-3">
                <span className="mono mt-0.5 flex h-6 w-6 shrink-0 items-center justify-center rounded-xs border border-border bg-raised text-[11px] text-muted">
                  {i + 1}
                </span>
                <span className="min-w-0">
                  <span className="block text-[13px] font-medium text-text">{step.title}</span>
                  <span className="mt-0.5 block text-[12.5px] leading-relaxed text-muted">
                    {step.body}
                  </span>
                </span>
              </li>
            ))}
          </ol>
          <div className="mt-7 flex flex-wrap items-center gap-2">
            <ButtonLink to="/knowledge/add" variant="primary" leadingIcon={Database}>
              Conectar mis datos
            </ButtonLink>
            {session?.workspaceKind === "demo" && (
              <ButtonLink to="/chat" variant="secondary" leadingIcon={Sparkle}>
                Explorar demo
              </ButtonLink>
            )}
            {resumeId && (
              <ButtonLink to={`/knowledge/add/${resumeId}`} variant="ghost" leadingIcon={ArrowRight}>
                Continuar donde lo dejé
              </ButtonLink>
            )}
          </div>
        </Panel>
      </div>
    );
  }

  return (
    <div>
      <PageHeader
        title="Panel general"
        subtitle="Salud del sistema, consumo del período y lo que pide atención en tu workspace."
        actions={
          <>
            <ButtonLink to="/chat" variant="secondary" size="sm" leadingIcon={Sparkle}>
              Probar
            </ButtonLink>
            <ButtonLink to="/usage" variant="ghost" size="sm" leadingIcon={ChartLineUp}>
              Analítica
            </ButtonLink>
          </>
        }
      />

      <ErrorInline message={error} />

      {!loading && attentionSessions.length > 0 && (
        <WarningInline>
          {attentionSessions[0].warning || "Zent tiene datos sin revisar de tu última fuente."}{" "}
          <Link className="font-medium underline" to={`/knowledge/add/${attentionSessions[0].id}`}>
            Revisar ahora
          </Link>
        </WarningInline>
      )}

      <KnowledgePillarLinks
        title="Conocimiento"
        subtitle="Resumen, fuentes, semántica y mejora — el viaje de tus datos."
      />

      {loading ? (
        <div className="mt-4 flex flex-col gap-4" aria-hidden>
          <Skeleton className="h-[132px] rounded-lg" />
          <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
            {Array.from({ length: 4 }).map((_, i) => (
              <Skeleton key={i} className="h-[92px] rounded-lg" />
            ))}
          </div>
          <div className="grid gap-4 xl:grid-cols-3">
            <Skeleton className="h-[320px] rounded-lg xl:col-span-2" />
            <Skeleton className="h-[320px] rounded-lg" />
          </div>
        </div>
      ) : (
        <div className="mt-4 flex flex-col gap-4">
          {/* Foco: pulso del workspace */}
          <Panel className="p-5 sm:p-6">
            <div className="flex flex-col gap-6 lg:flex-row lg:items-start lg:justify-between">
              <div className="min-w-0">
                <p className="eyebrow mb-2">Pulso del workspace</p>
                <div className="flex items-baseline gap-3">
                  <p
                    className={cn(
                      "text-display",
                      health === "ok" ? "text-ok" : "text-danger"
                    )}
                  >
                    {health === "ok" ? "Operativo" : "Degradado"}
                  </p>
                  <StatusDot tone={health === "ok" ? "ok" : "danger"} className="mb-2" />
                </div>
                <p className="mt-1.5 text-[13px] text-muted">
                  {outages.length === 0
                    ? "Todos los servicios responden."
                    : `${outages.length} de ${SERVICES.length} servicios con problemas.`}
                </p>
                <ul className="mt-4 flex flex-wrap items-center gap-x-4 gap-y-2">
                  {SERVICES.map((service) => {
                    const value = checks[service];
                    const ok = value === "ok";
                    return (
                      <li key={service} className="flex items-center gap-1.5 text-[12px]">
                        <StatusDot tone={!value ? "neutral" : ok ? "ok" : "danger"} />
                        <span className="text-muted">{SERVICE_LABELS[service]}</span>
                        <span className="sr-only">
                          {!value ? "sin verificar" : ok ? "saludable" : "degradado"}
                        </span>
                      </li>
                    );
                  })}
                </ul>
              </div>

              <div className="min-w-0 lg:w-[320px] lg:shrink-0">
                {quotaPct !== null ? (
                  <Progress
                    value={quotaPct}
                    tone={quotaTone === "accent" ? "accent" : quotaTone}
                    label={`Uso del período · ${fmtNum(used)} de ${fmtNum(limit ?? 0)}`}
                    showValue
                  />
                ) : (
                  <p className="text-[13px] text-muted">
                    <span className="mono text-text">{fmtNum(used)}</span> consultas este período · sin
                    tope definido
                  </p>
                )}
                <div className="mt-4 flex items-center justify-between gap-3 border-t border-border pt-4">
                  <span className="text-[13px]">
                    {pending === 0 ? (
                      <span className="text-muted">Sin pendientes que revisar</span>
                    ) : (
                      <span className="text-warn">
                        {pending} {pending === 1 ? "cosa pide" : "cosas piden"} atención
                      </span>
                    )}
                  </span>
                  {pending > 0 && (
                    <Link
                      to="/knowledge/sources"
                      className="shrink-0 text-[13px] font-medium text-accent hover:underline"
                    >
                      Revisar
                    </Link>
                  )}
                </div>
              </div>
            </div>
          </Panel>

          {/* Métricas secundarias, deliberadamente más chicas que el foco */}
          <MetricGrid cols={4}>
            <Metric
              size="md"
              label="Consultas · 30 días"
              value={fmtNum(usage?.totals.requests ?? 0)}
              hint={
                usage?.totals.tokens
                  ? `${fmtNum(usage.totals.tokens)} tokens generados`
                  : "sin consumo aún"
              }
              icon={Lightning}
            />
            <Metric
              size="md"
              label="Latencia media"
              value={usage?.totals.avg_latency_ms ? fmtLatency(usage.totals.avg_latency_ms) : "—"}
              hint="últimos 30 días"
              icon={Timer}
            />
            <Metric
              size="md"
              label="Agentes"
              value={agentCount != null ? fmtNum(agentCount) : "—"}
              hint={agentCount === 0 ? "todavía no creaste ninguno" : "en este workspace"}
              icon={Robot}
            />
            <Metric
              size="md"
              label="Calidad de IA"
              value={quality?.total_evaluations ? `${quality.approval_rate}%` : "—"}
              tone={
                quality?.total_evaluations
                  ? quality.approval_rate >= 70
                    ? "ok"
                    : "warn"
                  : "default"
              }
              hint={
                quality?.total_evaluations
                  ? `${fmtNum(quality.total_evaluations)} evaluaciones aprobadas`
                  : "sin evaluaciones todavía"
              }
              icon={Star}
            />
          </MetricGrid>

          <div className="grid gap-4 xl:grid-cols-3">
            <Panel className="xl:col-span-2">
              <PanelHeader
                title="Consultas por día"
                description="Volumen diario de consultas a tus agentes."
                actions={
                  <span className="mono text-[11px] text-faint">últimos 30 días</span>
                }
              />
              <div className="p-4">
                {daily.length === 0 ? (
                  <EmptyState
                    icon={ChartLineUp}
                    title="Aún no hay consultas"
                    body="Cuando hagas preguntas en el Playground, vas a ver acá la actividad diaria."
                    action={
                      <ButtonLink to="/chat" variant="secondary" size="sm" trailingIcon={ArrowRight}>
                        Probar el Playground
                      </ButtonLink>
                    }
                  />
                ) : (
                  <Suspense
                    fallback={
                      <div className="flex h-[240px] items-center justify-center">
                        <Skeleton className="h-full w-full rounded-md" />
                      </div>
                    }
                  >
                    <UsageChart daily={daily} />
                  </Suspense>
                )}
              </div>
            </Panel>

            <Panel>
              <PanelHeader
                title="Consultas recientes"
                actions={
                  <Link
                    to="/usage"
                    className="flex items-center gap-1 text-xs text-accent hover:underline"
                  >
                    Analítica <ArrowRight size={12} aria-hidden />
                  </Link>
                }
              />
              {recentQueries.length === 0 ? (
                <EmptyState
                  compact
                  icon={ListBullets}
                  title="Sin consultas recientes"
                  body="Tus últimas preguntas y su rendimiento aparecen acá."
                />
              ) : (
                <ul className="px-2 pb-2">
                  {recentQueries.slice(0, 6).map((r) => (
                    <li
                      key={r.id}
                      className="flex items-center justify-between gap-3 border-b border-border-soft px-3 py-2.5 last:border-b-0"
                    >
                      <div className="min-w-0">
                        <p className="truncate text-[12.5px] text-muted">
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
            </Panel>
          </div>

          <div className="grid gap-4 xl:grid-cols-3">
            <div className="xl:col-span-2">
              <AttentionList
                items={issues}
                emptyBody="No se detectaron problemas en tu workspace."
              />
            </div>

            <Panel>
              <PanelHeader
                title="Indexado por demanda"
                actions={<span className="mono text-[11px] text-faint">30 días</span>}
              />
              {lazyEvents.length === 0 ? (
                <EmptyState
                  compact
                  icon={Lightning}
                  title="Sin indexados automáticos"
                  body="Cuando una pregunta necesite datos no sincronizados, el sistema los indexa y queda registrado acá."
                />
              ) : (
                <ul className="px-2 pb-2">
                  {lazyEvents.map((ev, i) => (
                    <li
                      key={`${ev.at}-${i}`}
                      className="border-b border-border-soft px-3 py-3 last:border-b-0"
                    >
                      <div className="flex flex-wrap items-center justify-between gap-2">
                        <span className="mono text-xs text-accent">
                          {(ev.tables || []).join(", ") || "—"}
                        </span>
                        <span className="flex items-center gap-2 text-[11px] text-faint">
                          {ev.rows_indexed > 0 && <span className="mono">{ev.rows_indexed} filas</span>}
                          · {timeAgo(ev.at)}
                        </span>
                      </div>
                      {ev.query_preview && (
                        <p className="mt-1 truncate text-[12.5px] text-muted" title={ev.query_preview}>
                          «{ev.query_preview}»
                        </p>
                      )}
                    </li>
                  ))}
                </ul>
              )}
            </Panel>
          </div>

          <div className="flex flex-col gap-3 border-t border-border pt-4 text-xs text-muted sm:flex-row sm:items-center sm:justify-between">
            <p className="flex flex-wrap items-center gap-x-3 gap-y-1">
              <span>
                <span className="mono text-text">{fmtNum(usage?.totals.requests ?? 0)}</span> consultas
              </span>
              <span aria-hidden className="text-ghost">
                ·
              </span>
              <span>
                <span className="mono text-text">{fmtNum(usage?.totals.tokens ?? 0)}</span> tokens
              </span>
              <span aria-hidden className="text-ghost">
                ·
              </span>
              <span>
                <span className="mono text-text">
                  {usage?.totals.avg_latency_ms ? fmtLatency(usage.totals.avg_latency_ms) : "—"}
                </span>{" "}
                de latencia media
              </span>
              <span className="text-faint">en los últimos 30 días</span>
            </p>
            <p className="flex flex-wrap items-center gap-x-4 gap-y-1">
              {sub?.trial_end && (
                <span className="flex items-center gap-1.5">
                  <CalendarBlank size={13} aria-hidden />
                  Trial hasta {new Date(sub.trial_end).toLocaleDateString()}
                </span>
              )}
              <span className="flex items-center gap-1.5">
                Plan <span className="text-text">{sub?.plan_name || sub?.status || "—"}</span>
              </span>
              <Link to="/billing" className="font-medium text-accent hover:underline">
                Facturación
              </Link>
              <Tooltip label="Estado de los servicios de plataforma">
                <span className="flex items-center gap-1.5">
                  <Heartbeat size={13} aria-hidden />
                  <StatusDot tone={health === "ok" ? "ok" : "danger"} />
                  {health === "ok" ? "Operativo" : "Degradado"}
                </span>
              </Tooltip>
            </p>
          </div>

          <p className="flex flex-wrap items-center gap-x-4 gap-y-2 text-xs text-faint">
            <span className="eyebrow">Atajos</span>
            <Link to="/knowledge/add" className="inline-flex items-center gap-1 hover:text-text">
              <Database size={13} aria-hidden />
              Añadir conocimiento
            </Link>
            <Link to="/agents" className="inline-flex items-center gap-1 hover:text-text">
              <Robot size={13} aria-hidden />
              Crear un agente
            </Link>
            <Link to="/connectors" className="inline-flex items-center gap-1 hover:text-text">
              <Plugs size={13} aria-hidden />
              Conectores
            </Link>
            <Link to="/keys" className="inline-flex items-center gap-1 hover:text-text">
              <Sparkle size={13} aria-hidden />
              Credenciales de API
            </Link>
          </p>
        </div>
      )}
    </div>
  );
}
