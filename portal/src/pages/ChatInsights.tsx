import { ArrowClockwise, ChatText, Warning, WarningCircle } from "@phosphor-icons/react";
import { useEffect, useState } from "react";
import { api } from "../api";
import { useAuth } from "../auth";
import {
  Button,
  EmptyState,
  ErrorInline,
  Metric,
  MetricGrid,
  PageHeader,
  Panel,
  PanelHeader,
  Skeleton,
} from "../components/ui";
import { fmtLatency, fmtNum } from "../lib/format";

type Funnel = { total_messages: number; total_sessions: number; active_sessions: number; resolved_sessions: number; resolution_rate: number; escalations: number };
type Topics = { total_user_messages: number; topics: { topic: string; message_count: number; share: number }[] };
type Friction = { summary: { repetitive: number; redirects: number; escalations: number; friction_index: number }; repetitive_sessions: { session_id: string; messages: number }[]; redirect_sessions: { session_id: string; intents: number }[] };
type Channels = { channels: { channel: string; messages: number; avg_latency_ms: number; success_rate: number }[] };

function ChatInsightsSkeleton() {
  return (
    <div className="flex flex-col gap-4" aria-hidden>
      <div className="grid gap-4 lg:grid-cols-3">
        <Skeleton className="h-[248px] rounded-lg lg:col-span-2" />
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
          {Array.from({ length: 4 }).map((_, i) => (
            <Skeleton key={i} className="h-[104px] rounded-lg" />
          ))}
        </div>
      </div>
      <div className="grid gap-4 lg:grid-cols-2">
        <Skeleton className="h-[216px] rounded-lg" />
        <Skeleton className="h-[216px] rounded-lg" />
      </div>
      <Skeleton className="h-[180px] rounded-lg" />
    </div>
  );
}

function ShareBar({ share }: { share: number }) {
  const pct = Math.max(0, Math.min(100, share));
  return (
    <div className="progress-track mt-1.5">
      <div className="progress-fill" style={{ width: `${pct}%` }} />
    </div>
  );
}

export default function ChatInsightsPage() {
  const { session } = useAuth();
  const [funnel, setFunnel] = useState<Funnel | null>(null);
  const [topics, setTopics] = useState<Topics | null>(null);
  const [friction, setFriction] = useState<Friction | null>(null);
  const [channels, setChannels] = useState<Channels | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  async function load() {
    if (!session) return;
    setError("");
    try {
      const [f, t, fr, c] = await Promise.all([
        api<Funnel>("/api/v1/chat-insights/funnel", { token: session.token, organizationId: session.organizationId }),
        api<Topics>("/api/v1/chat-insights/topics", { token: session.token, organizationId: session.organizationId }),
        api<Friction>("/api/v1/chat-insights/friction", { token: session.token, organizationId: session.organizationId }),
        api<Channels>("/api/v1/chat-insights/channels", { token: session.token, organizationId: session.organizationId }),
      ]);
      setFunnel(f);
      setTopics(t);
      setFriction(fr);
      setChannels(c);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Error");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    void load();
    const id = setInterval(() => void load(), 20000);
    return () => clearInterval(id);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [session]);

  const sessions = funnel?.total_sessions ?? 0;
  const stages = [
    { label: "Sesiones", value: sessions, share: sessions > 0 ? 100 : 0 },
    {
      label: "Sesiones activas (≥2 mensajes)",
      value: funnel?.active_sessions ?? 0,
      share: sessions > 0 ? ((funnel?.active_sessions ?? 0) / sessions) * 100 : 0,
    },
    {
      label: "Resueltas (rating ≥4)",
      value: funnel?.resolved_sessions ?? 0,
      share: sessions > 0 ? ((funnel?.resolved_sessions ?? 0) / sessions) * 100 : 0,
    },
  ];
  const topicList = topics?.topics ?? [];
  const channelList = channels?.channels ?? [];
  const escalations = friction?.summary.escalations ?? 0;

  return (
    <div className="space-y-6">
      <PageHeader title="Chat Insights" subtitle="Embudo conversacional, temas de consultas, fricción y comparativa por canal." />
      {error && funnel ? <ErrorInline message={error} /> : null}
      {loading ? (
        <ChatInsightsSkeleton />
      ) : !funnel && error ? (
        <Panel>
          <EmptyState
            icon={WarningCircle}
            title="No pudimos cargar la analítica de chat"
            body={error}
            hint="Revisá la conexión y volvé a intentar."
            action={
              <Button variant="secondary" leadingIcon={ArrowClockwise} onClick={() => void load()}>
                Reintentar
              </Button>
            }
          />
        </Panel>
      ) : (
        <div className="flex flex-col gap-4">
          <div className="grid gap-4 lg:grid-cols-3">
            {/* Foco: dónde se pierden o resuelven las conversaciones */}
            <Panel className="lg:col-span-2">
              <PanelHeader
                title="Embudo conversacional"
                description="De la sesión a la conversación resuelta en los últimos 30 días."
                actions={<span className="mono text-[11px] text-faint">30 días</span>}
              />
              <div className="p-4">
                <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
                  <p className={sessions === 0 ? "text-display text-muted" : "text-display text-text"}>
                    {funnel?.resolution_rate ?? 0}%
                  </p>
                  <p className="text-[13px] text-muted">
                    tasa de resolución de {fmtNum(sessions)} sesiones
                  </p>
                </div>
                <ul className="mt-5 flex flex-col gap-4">
                  {stages.map((stage) => (
                    <li key={stage.label}>
                      <div className="flex flex-wrap items-baseline justify-between gap-x-3 gap-y-1">
                        <span className="text-[13px] text-text">{stage.label}</span>
                        <span className="text-xs text-faint tabular-nums">
                          {fmtNum(stage.value)}
                          {sessions > 0 ? ` · ${Math.round(stage.share)}%` : ""}
                        </span>
                      </div>
                      <ShareBar share={stage.share} />
                    </li>
                  ))}
                </ul>
                {sessions === 0 && (
                  <p className="mt-4 text-xs text-muted">
                    Sin sesiones en los últimos 30 días: el embudo se completa cuando el chat reciba consultas.
                  </p>
                )}
              </div>
            </Panel>

            {/* Demotadas: acompañan al embudo */}
            <MetricGrid cols={2}>
              <Metric
                size="md"
                label="Sesiones"
                value={fmtNum(sessions)}
                hint="últimos 30 días"
                icon={ChatText}
              />
              <Metric
                size="md"
                label="Mensajes"
                value={fmtNum(funnel?.total_messages ?? 0)}
                hint="usuario y asistente"
              />
              <Metric
                size="md"
                label="Sesiones activas"
                value={fmtNum(funnel?.active_sessions ?? 0)}
                hint="con 2 o más mensajes"
              />
              <Metric
                size="md"
                label="Escalaciones"
                value={fmtNum(escalations)}
                tone={escalations > 0 ? "warn" : "default"}
                hint={escalations > 0 ? "requieren revisión" : "sin escalaciones"}
                icon={Warning}
              />
            </MetricGrid>
          </div>

          <div className="grid gap-4 lg:grid-cols-2">
            {/* Temas: share real por tema */}
            <Panel>
              <PanelHeader
                title="Temas"
                description={`Sobre ${fmtNum(topics?.total_user_messages ?? 0)} consultas de usuario.`}
              />
              <div className="p-4">
                {topicList.length === 0 ? (
                  <EmptyState
                    compact
                    icon={ChatText}
                    title="Sin temas detectados"
                    body="Usa el copilot para que Zent agrupe las consultas por tema."
                  />
                ) : (
                  <ul className="flex flex-col gap-3.5">
                    {topicList.map((t) => (
                      <li key={t.topic}>
                        <div className="flex flex-wrap items-baseline justify-between gap-x-3 gap-y-1">
                          <span className="text-[13px] text-text">{t.topic}</span>
                          <span className="text-xs text-faint tabular-nums">
                            {fmtNum(t.message_count)} · {t.share}%
                          </span>
                        </div>
                        <ShareBar share={t.share} />
                      </li>
                    ))}
                  </ul>
                )}
              </div>
            </Panel>

            {/* Fricción: sesiones repetitivas y redirecciones */}
            <Panel>
              <PanelHeader
                title="Fricción"
                description="Señales de que la conversación no avanzó en el primer intento."
              />
              <div className="p-4">
                <div className="flex flex-wrap items-end justify-between gap-3">
                  <div>
                    <p className="eyebrow">Índice de fricción</p>
                    <p className="mt-1 text-[22px] leading-none font-semibold text-text tabular-nums">
                      {friction?.summary.friction_index ?? 0}
                    </p>
                  </div>
                  {escalations > 0 && (
                    <span className="badge badge-pending">
                      <WarningCircle size={12} weight="fill" aria-hidden />
                      {fmtNum(escalations)} escalaciones
                    </span>
                  )}
                </div>
                <dl className="mt-4 divide-y divide-border-soft">
                  <div className="flex items-center justify-between gap-3 py-2.5 text-[13px]">
                    <dt className="text-muted">Sesiones repetitivas</dt>
                    <dd className="tabular-nums text-text">{fmtNum(friction?.summary.repetitive ?? 0)}</dd>
                  </div>
                  <div className="flex items-center justify-between gap-3 py-2.5 text-[13px]">
                    <dt className="text-muted">Redirecciones (≥3 intenciones)</dt>
                    <dd className="tabular-nums text-text">{fmtNum(friction?.summary.redirects ?? 0)}</dd>
                  </div>
                  <div className="flex items-center justify-between gap-3 py-2.5 text-[13px]">
                    <dt className="text-muted">Escalaciones</dt>
                    <dd className="tabular-nums text-text">{fmtNum(escalations)}</dd>
                  </div>
                </dl>
                {(friction?.repetitive_sessions ?? []).length > 0 && (
                  <>
                    <p className="eyebrow mt-4">Sesiones repetitivas</p>
                    <ul className="mt-1 divide-y divide-border-soft">
                      {(friction?.repetitive_sessions ?? []).slice(0, 3).map((r) => (
                        <li key={r.session_id} className="flex items-center justify-between gap-3 py-2 text-xs">
                          <span className="mono text-faint">{r.session_id.slice(0, 8)}…</span>
                          <span className="text-muted tabular-nums">{r.messages} mensajes</span>
                        </li>
                      ))}
                    </ul>
                  </>
                )}
              </div>
            </Panel>
          </div>

          {/* Canales: comparativa real */}
          <Panel>
            <PanelHeader
              title="Canales"
              description="Volumen, latencia media y tasa de éxito por canal de entrada."
            />
            {channelList.length === 0 ? (
              <EmptyState
                compact
                icon={ChatText}
                title="Sin actividad por canal"
                body="Cuando el chat reciba consultas vas a ver acá la comparativa por canal."
              />
            ) : (
              <div className="overflow-x-auto">
                <table className="table min-w-[520px]">
                  <caption className="sr-only">
                    Mensajes, latencia media y tasa de éxito por canal
                  </caption>
                  <thead>
                    <tr>
                      <th scope="col">Canal</th>
                      <th scope="col" className="text-right">Mensajes</th>
                      <th scope="col" className="text-right">Latencia media</th>
                      <th scope="col">Éxito</th>
                    </tr>
                  </thead>
                  <tbody>
                    {channelList.map((ch) => (
                      <tr key={ch.channel}>
                        <td className="font-medium">{ch.channel}</td>
                        <td className="mono text-right">{fmtNum(ch.messages)}</td>
                        <td className="mono text-right">{fmtLatency(ch.avg_latency_ms)}</td>
                        <td>
                          <div className="flex items-center gap-2">
                            <div className="progress-track w-24">
                              <div
                                className="progress-fill"
                                style={{ width: `${Math.max(0, Math.min(100, ch.success_rate))}%` }}
                              />
                            </div>
                            <span className="mono text-xs text-muted tabular-nums">
                              {ch.success_rate}%
                            </span>
                          </div>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </Panel>
        </div>
      )}
    </div>
  );
}
