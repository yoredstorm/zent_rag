import {
  ArrowClockwise,
  ArrowCounterClockwise,
  ChatCircle,
  CheckCircle,
  ListChecks,
  Question,
  SealCheck,
  Sparkle,
  TrendUp,
  WarningCircle,
  XCircle,
} from "@phosphor-icons/react";
import { useCallback, useEffect, useState } from "react";
import { api } from "../../api";
import { useAuth } from "../../auth";
import {
  Badge,
  Button,
  ButtonLink,
  EmptyState,
  ErrorInline,
  KeyValue,
  Metric,
  MetricGrid,
  PageHeader,
  Panel,
  PanelHeader,
  Progress,
  Skeleton,
} from "../../components/ui";
import { QualityLayout } from "../../components/QualityLayout";
import { fmtNum } from "../../lib/format";

/** Mismo vocabulario que Context Gaps: código del engine → lenguaje de negocio. */
const GAP_TYPE_LABELS: Record<string, string> = {
  MISSING_SOURCE: "Falta una fuente",
  MISSING_TABLE: "Falta una tabla",
  MISSING_FIELD: "Falta un campo",
  MISSING_RELATIONSHIP: "Falta una relación",
  MISSING_BUSINESS_TERM: "Falta definición de negocio",
  MISSING_METRIC: "Falta una métrica",
  UNDEFINED_ENUM: "Valor sin definir",
  AMBIGUOUS_TERM: "Término ambiguo",
  STALE_SOURCE: "Fuente desactualizada",
  LOW_DATA_QUALITY: "Calidad de datos baja",
  SOURCE_CONFLICT: "Fuentes en conflicto",
  PERMISSION_LIMITATION: "Limitación de permisos",
  UNSUPPORTED_OPERATION: "Operación no soportada",
};

type Trends = {
  days: number;
  total_queries: number;
  answerable_queries: number;
  abstained_queries: number;
  answerability_rate: number;
  unsupported_question_rate: number;
  context_gaps_open: number;
  context_gaps_resolved: number;
  gap_resolution_rate: number;
  improvements_open: number;
  most_impactful_missing_concepts: {
    title: string;
    gap_type?: string;
    affected_queries: number;
  }[];
  knowledge_approvals_30d: number;
  evaluation_replays: { total: number; pass: number; warn: number; fail: number; unknown: number };
};

export default function EvaluationImpactPage() {
  const { session } = useAuth();
  const [trends, setTrends] = useState<Trends | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  const load = useCallback(() => {
    if (!session) return;
    setLoading(true);
    api<Trends>("/api/v1/learning/analytics?days=30")
      .then((data) => {
        setTrends(data);
        setError("");
      })
      .catch((e) => setError(String(e)))
      .finally(() => setLoading(false));
  }, [session]);

  useEffect(() => load(), [load]);

  const concepts = trends?.most_impactful_missing_concepts ?? [];
  const maxAffected = concepts.reduce((max, concept) => Math.max(max, concept.affected_queries), 0);
  const replays = trends?.evaluation_replays;

  return (
    <QualityLayout>
      <PageHeader
        title="Impacto del aprendizaje"
        subtitle="Métricas reales del ciclo gobernado (nada inventado)."
      />

      <div className="flex flex-col gap-4">
        <ErrorInline message={error} className="mb-0">
          <span className="flex flex-wrap items-center gap-3">
            <span>{error}</span>
            <Button size="sm" variant="secondary" leadingIcon={ArrowClockwise} onClick={load}>
              Reintentar
            </Button>
          </span>
        </ErrorInline>

        {loading ? (
          <div className="flex flex-col gap-4" aria-busy="true">
            <Skeleton className="h-[124px] rounded-lg" />
            <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-4">
              {Array.from({ length: 4 }).map((_, i) => (
                <Skeleton key={i} className="h-[96px] rounded-lg" />
              ))}
            </div>
            <Skeleton className="h-[220px] rounded-lg" />
          </div>
        ) : !trends ? null : (
          <>
            <Panel>
              <div className="flex flex-col gap-5 p-4 lg:flex-row lg:items-center lg:justify-between">
                {trends.total_queries === 0 ? (
                  <EmptyState
                    compact
                    icon={ChatCircle}
                    title="Sin consultas en el período"
                    body="Cuando Zent responda consultas reales vas a ver acá cuántas quedaron soportadas por tu conocimiento."
                  />
                ) : (
                  <>
                    <div className="min-w-0">
                      <p className="eyebrow">
                        Respuestas soportadas · últimos {trends.days} días
                      </p>
                      <div className="mt-2 flex flex-wrap items-baseline gap-x-3 gap-y-1">
                        <span className="stat-value">{trends.answerability_rate}%</span>
                        <span className="text-sm text-muted">
                          {fmtNum(trends.answerable_queries)} de {fmtNum(trends.total_queries)}{" "}
                          consultas
                        </span>
                      </div>
                      <p className="mt-2 text-[13px] leading-relaxed text-muted">
                        {trends.unsupported_question_rate}% quedó sin respuesta y alimenta gaps o
                        mejoras. Ese es el trabajo pendiente del ciclo.
                      </p>
                    </div>
                    <div className="w-full max-w-[340px] shrink-0">
                      <Progress
                        value={trends.answerability_rate}
                        label="Respuestas soportadas por el conocimiento"
                        tone={trends.answerability_rate >= 70 ? "ok" : "warn"}
                      />
                      <p className="mt-2 text-xs text-faint">
                        Answerability real: solo consultas registradas por el engine.
                      </p>
                    </div>
                  </>
                )}
              </div>
            </Panel>

            <MetricGrid cols={4}>
              <Metric
                size="md"
                label="Consultas totales"
                value={fmtNum(trends.total_queries)}
                icon={ChatCircle}
                hint={`últimos ${trends.days} días`}
              />
              <Metric
                size="md"
                label="Sin respuesta"
                value={fmtNum(trends.abstained_queries)}
                icon={Question}
                tone={trends.abstained_queries > 0 ? "warn" : "default"}
                hint={`${trends.unsupported_question_rate}% del período`}
              />
              <Metric
                size="md"
                label="Gaps abiertos"
                value={fmtNum(trends.context_gaps_open)}
                icon={ListChecks}
                tone={trends.context_gaps_open > 0 ? "warn" : "default"}
                hint={`${fmtNum(trends.context_gaps_resolved)} resueltos`}
              />
              <Metric
                size="md"
                label="Mejoras abiertas"
                value={fmtNum(trends.improvements_open)}
                icon={Sparkle}
                tone={trends.improvements_open > 0 ? "warn" : "default"}
                hint="mejoras sin resolver"
              />
            </MetricGrid>

            <div className="grid gap-4 lg:grid-cols-2">
              <Panel>
                <PanelHeader
                  title="Ciclo de gaps"
                  description="Qué se detectó y qué se resolvió en el período."
                />
                <div className="p-4">
                  <Progress
                    label="Resolución de gaps"
                    value={trends.gap_resolution_rate}
                    showValue
                    tone={trends.gap_resolution_rate >= 50 ? "ok" : "warn"}
                  />
                  <KeyValue
                    className="mt-4"
                    columns={2}
                    items={[
                      { key: "Gaps abiertos", value: fmtNum(trends.context_gaps_open) },
                      { key: "Gaps resueltos", value: fmtNum(trends.context_gaps_resolved) },
                      {
                        key: "Aprobaciones 30d",
                        value: fmtNum(trends.knowledge_approvals_30d),
                      },
                      {
                        key: "Mejoras abiertas",
                        value: fmtNum(trends.improvements_open),
                      },
                    ]}
                  />
                  <div className="mt-4">
                    <ButtonLink to="/evaluation/gaps" variant="secondary" size="sm">
                      Ver Context Gaps
                    </ButtonLink>
                  </div>
                </div>
              </Panel>

              <Panel>
                <PanelHeader
                  title="Replays de evaluación"
                  description="El conocimiento mejorado reejecutado contra casos reales."
                />
                {!replays || replays.total === 0 ? (
                  <EmptyState
                    compact
                    icon={ArrowCounterClockwise}
                    title="Sin replays en el período"
                    body="Cuando se reejecuten evaluaciones sobre conocimiento nuevo, vas a ver cuántas aprueban, quedan con avisos o fallan."
                  />
                ) : (
                  <div className="p-4">
                    <div className="flex flex-wrap gap-2">
                      <Badge tone="ok" icon={CheckCircle}>
                        Aprueba · {fmtNum(replays.pass)}
                      </Badge>
                      <Badge tone="warn" icon={WarningCircle}>
                        Con avisos · {fmtNum(replays.warn)}
                      </Badge>
                      <Badge tone="danger" icon={XCircle}>
                        Falla · {fmtNum(replays.fail)}
                      </Badge>
                      <Badge tone="neutral" icon={Question}>
                        Sin datos · {fmtNum(replays.unknown)}
                      </Badge>
                    </div>
                    <p className="mt-3 text-xs text-muted tabular-nums">
                      {fmtNum(replays.total)} evaluaciones reejecutadas en los últimos {trends.days}{" "}
                      días.
                    </p>
                  </div>
                )}
              </Panel>
            </div>

            <Panel>
              <PanelHeader
                title="Conceptos faltantes más impactantes"
                description="Pedidos en consultas sin respuesta, ordenados por consultas afectadas. Cerrarlos es lo que más desbloquea."
                actions={
                  <>
                    <Badge tone="info" icon={SealCheck}>
                      solo eventos reales
                    </Badge>
                    <ButtonLink to="/evaluation/gaps" variant="secondary" size="sm">
                      Resolver gaps
                    </ButtonLink>
                  </>
                }
              />
              {concepts.length === 0 ? (
                <EmptyState
                  compact
                  icon={TrendUp}
                  title="Sin conceptos faltantes"
                  body="Todavía no hay mejoras registradas con concepto asociado en el período."
                />
              ) : (
                <ul className="divide-y divide-border-soft">
                  {concepts.map((concept) => (
                    <li
                      key={`${concept.title}-${concept.gap_type ?? ""}`}
                      className="flex flex-col gap-2 px-4 py-3 sm:flex-row sm:items-center sm:justify-between"
                    >
                      <div className="min-w-0">
                        <p className="text-[13.5px] font-medium text-text">{concept.title}</p>
                        {concept.gap_type && (
                          <p className="mt-0.5 text-xs text-faint" title={concept.gap_type}>
                            {GAP_TYPE_LABELS[concept.gap_type] ?? concept.gap_type}
                          </p>
                        )}
                      </div>
                      <div className="flex shrink-0 items-center gap-3">
                        <span className="text-xs text-muted tabular-nums">
                          {fmtNum(concept.affected_queries)} consultas afectadas
                        </span>
                        <div className="w-24">
                          <Progress
                            value={concept.affected_queries}
                            max={maxAffected || concept.affected_queries}
                            label="Consultas afectadas"
                            tone="warn"
                          />
                        </div>
                      </div>
                    </li>
                  ))}
                </ul>
              )}
            </Panel>
          </>
        )}
      </div>
    </QualityLayout>
  );
}
