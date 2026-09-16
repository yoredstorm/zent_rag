import {
  ArrowClockwise,
  CheckCircle,
  Star,
  Target,
  ThumbsDown,
  ThumbsUp,
  Timer,
  WarningCircle,
  type Icon,
} from "@phosphor-icons/react";
import { useEffect, useState } from "react";
import { api } from "../api";
import { useAuth } from "../auth";
import {
  Badge,
  Button,
  ButtonLink,
  EmptyState,
  ErrorInline,
  Metric,
  MetricGrid,
  PageHeader,
  Panel,
  PanelHeader,
  Progress,
  Skeleton,
  type Tone,
} from "../components/ui";
import { QualityLayout } from "../components/QualityLayout";
import { fmtDateTime, fmtLatency, fmtNum } from "../lib/format";

type EvalStats = {
  period_days: number;
  total_evaluations: number;
  thumbs_up: number;
  thumbs_down: number;
  approval_rate: number;
  avg_latency_ms: number;
  avg_tokens: number;
  models_used: number;
};

type EvalRecent = {
  id: string;
  query: string;
  answer: string;
  role: string;
  rating: "up" | "down" | null;
  comment: string;
  model: string;
  total_tokens: number;
  latency_ms: number;
  method: string;
  created_at: string;
};

const RATING_META: Record<"up" | "down" | "none", { label: string; tone: Tone; icon: Icon }> = {
  up: { label: "Positivo", tone: "ok", icon: ThumbsUp },
  down: { label: "Negativo", tone: "danger", icon: ThumbsDown },
  none: { label: "Sin feedback", tone: "neutral", icon: Star },
};

export default function AiQualityPage() {
  const { session } = useAuth();
  const [stats, setStats] = useState<EvalStats | null>(null);
  const [recent, setRecent] = useState<EvalRecent[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [reloadKey, setReloadKey] = useState(0);

  useEffect(() => {
    if (!session) return;
    let cancelled = false;
    (async () => {
      setLoading(true);
      setError("");
      const [statsResult, recentResult] = await Promise.allSettled([
        api<EvalStats>("/api/v1/eval/stats?days=30", {
          token: session.token,
          organizationId: session.organizationId,
        }),
        api<EvalRecent[]>("/api/v1/eval/recent?limit=20", {
          token: session.token,
          organizationId: session.organizationId,
        }),
      ]);
      if (cancelled) return;
      if (statsResult.status === "fulfilled") {
        setStats(statsResult.value);
      } else {
        setStats(null);
        setError(
          statsResult.reason instanceof Error
            ? statsResult.reason.message
            : "No pudimos cargar las métricas de calidad."
        );
      }
      setRecent(recentResult.status === "fulfilled" ? recentResult.value || [] : []);
      setLoading(false);
    })();
    return () => {
      cancelled = true;
    };
  }, [session, reloadKey]);

  const needsAttention = recent.filter((r) => r.rating === "down");
  const hasData = Boolean(stats && stats.total_evaluations > 0);
  const periodDays = stats?.period_days ?? 30;
  const approval = stats?.approval_rate ?? 0;
  const thumbsDown = stats?.thumbs_down ?? 0;
  const thumbsUp = stats?.thumbs_up ?? 0;
  const total = stats?.total_evaluations ?? 0;

  return (
    <QualityLayout>
      <PageHeader
        title="Calidad de IA"
        subtitle="Mide y mejora la calidad de tus respuestas a partir del feedback real de los usuarios."
      />
      {error && (
        <ErrorInline className="mb-0">
          <span className="flex flex-wrap items-center gap-3">
            <span>{error}</span>
            <Button
              size="sm"
              variant="secondary"
              leadingIcon={ArrowClockwise}
              onClick={() => setReloadKey((key) => key + 1)}
            >
              Reintentar
            </Button>
          </span>
        </ErrorInline>
      )}

      <div className="mt-4 flex flex-col gap-4">
        {loading ? (
          <div className="flex flex-col gap-4" aria-busy="true">
            <Skeleton className="h-[124px] rounded-lg" />
            <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-4">
              {Array.from({ length: 4 }).map((_, i) => (
                <Skeleton key={i} className="h-[96px] rounded-lg" />
              ))}
            </div>
            <Skeleton className="h-[260px] rounded-lg" />
          </div>
        ) : !hasData && !error ? (
          <Panel>
            <EmptyState
              icon={Star}
              title="Aún no hay evaluaciones"
              body="Cuando los usuarios califiquen respuestas en el Playground o en tus aplicaciones, verás acá la calidad real: aprobación, latencia y casos que requieren atención."
              hint="Sin feedback no se calculan promedios: no mostramos números vacíos."
              action={
                <ButtonLink to="/chat" variant="primary">
                  Abrir Playground
                </ButtonLink>
              }
            />
          </Panel>
        ) : (
          <>
            <Panel>
              <div className="flex flex-col gap-5 p-4 lg:flex-row lg:items-center lg:justify-between">
                <div className="min-w-0">
                  <p className="eyebrow">Aprobación · últimos {periodDays} días</p>
                  <div className="mt-2 flex flex-wrap items-baseline gap-x-3 gap-y-1">
                    <span className="stat-value">{approval}%</span>
                    <span className="text-sm text-muted tabular-nums">
                      {fmtNum(thumbsUp)} de {fmtNum(total)} respuestas con voto positivo
                    </span>
                  </div>
                  <p className="mt-2 flex flex-wrap items-center gap-2 text-[13px] text-muted">
                    {thumbsDown > 0 ? (
                      <>
                        <Badge tone="danger" icon={ThumbsDown}>
                          {fmtNum(thumbsDown)} negativas
                        </Badge>
                        <span>
                          Revisá el detalle en «Requieren atención» para entender qué falló.
                        </span>
                      </>
                    ) : (
                      <>
                        <CheckCircle size={15} weight="fill" className="text-ok" aria-hidden />
                        <span>Sin feedback negativo en el período.</span>
                      </>
                    )}
                  </p>
                </div>
                <div className="w-full max-w-[340px] shrink-0">
                  <Progress
                    value={approval}
                    label="Proporción de votos positivos"
                    tone={approval >= 70 ? "ok" : "warn"}
                  />
                  <p className="mt-2 text-xs text-faint">
                    Se calcula solo sobre respuestas con voto. Sin votos no hay tasa.
                  </p>
                </div>
              </div>
            </Panel>

            <MetricGrid cols={4}>
              <Metric
                size="md"
                label="Evaluaciones"
                value={fmtNum(total)}
                icon={Target}
                hint={`últimos ${periodDays} días · ${fmtNum(stats?.models_used ?? 0)} modelos`}
              />
              <Metric
                size="md"
                label="Feedback positivo"
                value={fmtNum(thumbsUp)}
                icon={ThumbsUp}
                tone="ok"
              />
              <Metric
                size="md"
                label="Feedback negativo"
                value={fmtNum(thumbsDown)}
                icon={ThumbsDown}
                tone={thumbsDown > 0 ? "danger" : "default"}
              />
              <Metric
                size="md"
                label="Latencia media"
                value={fmtLatency(stats?.avg_latency_ms ?? 0)}
                icon={Timer}
                hint={`${fmtNum(stats?.avg_tokens ?? 0)} tokens promedio`}
              />
            </MetricGrid>

            <div className="grid gap-4 xl:grid-cols-3">
              <Panel className="xl:col-span-2">
                <PanelHeader
                  title="Evaluaciones recientes"
                  actions={
                    <span className="text-xs text-faint tabular-nums">
                      últimas {recent.length}
                    </span>
                  }
                />
                {recent.length === 0 ? (
                  <EmptyState
                    compact
                    icon={Star}
                    title="Sin evaluaciones recientes"
                    body="Las últimas respuestas con feedback aparecerán acá, con modelo, latencia y tokens."
                  />
                ) : (
                  <ul className="divide-y divide-border-soft">
                    {recent.map((r) => {
                      const meta = RATING_META[r.rating ?? "none"];
                      return (
                        <li key={r.id} className="flex flex-col gap-1.5 px-4 py-3">
                          <div className="flex flex-wrap items-center gap-2">
                            <Badge tone={meta.tone} icon={meta.icon}>
                              {meta.label}
                            </Badge>
                            <span
                              className="mono truncate text-xs text-faint"
                              title={r.model || "modelo sin dato"}
                            >
                              {r.model || "modelo sin dato"}
                            </span>
                            <span className="ml-auto shrink-0 text-xs text-faint tabular-nums">
                              {fmtDateTime(r.created_at)}
                            </span>
                          </div>
                          <p className="truncate text-[13px] text-text" title={r.query}>
                            «{r.query}»
                          </p>
                          <p className="text-xs text-faint tabular-nums">
                            {fmtLatency(r.latency_ms)} · {fmtNum(r.total_tokens)} tokens ·{" "}
                            {r.role}
                          </p>
                        </li>
                      );
                    })}
                  </ul>
                )}
              </Panel>

              <Panel>
                <PanelHeader
                  title="Requieren atención"
                  description="Respuestas con voto negativo en las últimas 20."
                  actions={
                    needsAttention.length > 0 ? (
                      <Badge tone="danger" icon={WarningCircle}>
                        {needsAttention.length}
                      </Badge>
                    ) : undefined
                  }
                />
                {needsAttention.length === 0 ? (
                  <EmptyState
                    compact
                    icon={CheckCircle}
                    title="Sin feedback negativo"
                    body="Ninguna de las últimas evaluaciones tiene voto negativo."
                  />
                ) : (
                  <ul className="divide-y divide-border-soft">
                    {needsAttention.slice(0, 8).map((r) => (
                      <li key={r.id} className="flex flex-col gap-1 px-4 py-3">
                        <p className="truncate text-[13px] text-text" title={r.query}>
                          «{r.query}»
                        </p>
                        {r.comment && (
                          <p
                            className="flex items-start gap-1.5 text-xs leading-relaxed text-warn"
                            title={r.comment}
                          >
                            <ThumbsDown size={12} weight="fill" aria-hidden className="mt-0.5 shrink-0" />
                            <span>{r.comment}</span>
                          </p>
                        )}
                        <p className="text-xs text-faint tabular-nums">
                          {fmtDateTime(r.created_at)}
                        </p>
                      </li>
                    ))}
                  </ul>
                )}
              </Panel>
            </div>
          </>
        )}
      </div>
    </QualityLayout>
  );
}
