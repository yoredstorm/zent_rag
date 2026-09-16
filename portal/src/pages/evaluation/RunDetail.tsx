import {
  ArrowLeft,
  ArrowCounterClockwise,
  Binoculars,
  CheckCircle,
  ListChecks,
  Sparkle,
  WarningCircle,
  XCircle,
} from "@phosphor-icons/react";
import { useEffect, useMemo, useState } from "react";
import { useParams } from "react-router-dom";
import { api } from "../../api";
import { useAuth } from "../../auth";
import {
  Badge,
  Button,
  ButtonLink,
  DataTable,
  Drawer,
  EmptyState,
  ErrorInline,
  IconButton,
  InfoInline,
  KeyValue,
  Metric,
  MetricGrid,
  PageHeader,
  Panel,
  Skeleton,
  StatusBadge,
  Tabs,
  TabsContent,
  TabsList,
  TabsTrigger,
  type Column,
  type SortState,
} from "../../components/ui";
import { QualityLayout } from "../../components/QualityLayout";
import { fmtCurrency, fmtDateTime, fmtLatency, fmtNum } from "../../lib/format";

type RetrievedChunk = {
  content?: string;
  score?: number | null;
  metadata?: Record<string, unknown>;
};

type CaseRow = {
  case_id: string;
  question: string;
  expected_sources?: string[];
  expected_answer?: string | null;
  retrieved?: RetrievedChunk[];
  actual?: string;
  answer?: string;
  status?: string;
  target?: Record<string, unknown>;
  scores?: Record<string, number | null>;
  metrics?: Record<string, number | null>;
  latency_ms?: number | null;
  cost?: number | null;
  error?: string | null;
};

type RunDetail = {
  run_id: string;
  dataset_name?: string;
  created_at?: string;
  total_cases?: number;
  failed_cases?: number;
  quality?: Record<string, number | boolean | string | null>;
  performance?: {
    latency?: {
      avg_ms?: number;
      p50_ms?: number;
      p95_ms?: number;
      count?: number;
    };
    total_tokens?: number;
    avg_tokens?: number;
    total_cost?: number;
    avg_cost?: number;
  };
  cases?: CaseRow[];
};

type Failure = {
  case_id: string;
  question: string;
  answer: string | null;
  status?: string;
  score: number | null;
  hallucination_rate: number | null;
  reasons: string[];
};

type Evidence = { kind: "case"; row: CaseRow } | { kind: "failure"; row: Failure };

const QUALITY_METRICS: { key: string; label: string }[] = [
  { key: "faithfulness", label: "Fidelidad a las fuentes" },
  { key: "answer_relevance", label: "Relevancia de la respuesta" },
  { key: "context_relevance", label: "Relevancia del contexto" },
  { key: "retrieval_precision", label: "Precisión de retrieval" },
  { key: "retrieval_recall", label: "Cobertura de retrieval" },
  { key: "citation_accuracy", label: "Precisión de citas" },
  { key: "answerability_accuracy", label: "Answerability" },
  { key: "sql_accuracy", label: "Precisión SQL" },
];

function asNumber(value: unknown): number | null {
  return typeof value === "number" && !Number.isNaN(value) ? value : null;
}

function fmtScore(value: unknown): string | null {
  const num = asNumber(value);
  return num == null ? null : num.toFixed(3);
}

function caseScore(row: CaseRow): number | null {
  return asNumber(row.scores?.composite);
}

function caseLatency(row: CaseRow): number | null {
  return asNumber(row.latency_ms) ?? asNumber(row.metrics?.latency_ms);
}

function caseCost(row: CaseRow): number | null {
  return asNumber(row.cost) ?? asNumber(row.metrics?.cost);
}

function sortCases(rows: CaseRow[], sort: SortState): CaseRow[] {
  if (!sort) return rows;
  const dir = sort.dir === "asc" ? 1 : -1;
  const accessor = (row: CaseRow): string | number | null => {
    if (sort.key === "composite") return caseScore(row);
    if (sort.key === "latency") return caseLatency(row);
    if (sort.key === "cost") return caseCost(row);
    return row.question;
  };
  return [...rows].sort((a, b) => {
    const av = accessor(a);
    const bv = accessor(b);
    if (av == null && bv == null) return 0;
    if (av == null) return 1;
    if (bv == null) return -1;
    if (typeof av === "number" && typeof bv === "number") return (av - bv) * dir;
    return String(av).localeCompare(String(bv), "es") * dir;
  });
}

function p95Of(run: RunDetail): number | null {
  const latency = run.performance?.latency;
  if (!latency || latency.count === 0) return null;
  return asNumber(latency.p95_ms);
}

function p50Of(run: RunDetail): number | null {
  const latency = run.performance?.latency;
  if (!latency || latency.count === 0) return null;
  return asNumber(latency.p50_ms);
}

function avgLatencyOf(run: RunDetail): number | null {
  const latency = run.performance?.latency;
  if (!latency || latency.count === 0) return null;
  return asNumber(latency.avg_ms);
}

function EvidenceBody({ evidence }: { evidence: Evidence }) {
  if (evidence.kind === "failure") {
    const failure = evidence.row;
    return (
      <div className="flex flex-col gap-4">
        <div className="flex flex-wrap items-center gap-2">
          <StatusBadge status={failure.status || "completed"} />
          {failure.score != null && (
            <Badge tone="neutral">score {failure.score.toFixed(2)}</Badge>
          )}
          {failure.hallucination_rate != null && (
            <Badge
              tone={failure.hallucination_rate > 0 ? "danger" : "ok"}
              icon={failure.hallucination_rate > 0 ? WarningCircle : CheckCircle}
            >
              alucinación {failure.hallucination_rate.toFixed(2)}
            </Badge>
          )}
        </div>
        <ul className="flex flex-col gap-1.5">
          {failure.reasons.map((reason, i) => (
            <li key={i} className="flex items-start gap-2 text-[13px] text-danger">
              <WarningCircle size={14} aria-hidden className="mt-0.5 shrink-0" />
              <span className="mono">{reason}</span>
            </li>
          ))}
        </ul>
        {failure.answer && (
          <div>
            <p className="eyebrow mb-1.5">Respuesta del run</p>
            <p className="panel-quiet p-3 text-[13px] leading-relaxed whitespace-pre-wrap text-text">
              {failure.answer}
            </p>
          </div>
        )}
      </div>
    );
  }

  const row = evidence.row;
  const latency = caseLatency(row);
  const cost = caseCost(row);
  const metrics = row.metrics || {};
  const retrieved = row.retrieved || [];

  const metricItems = [
    latency != null ? { key: "Latencia", value: fmtLatency(latency), mono: true } : null,
    asNumber(metrics.retrieval_latency_ms) != null
      ? {
          key: "Latencia de retrieval",
          value: fmtLatency(asNumber(metrics.retrieval_latency_ms)),
          mono: true,
        }
      : null,
    asNumber(metrics.llm_latency_ms) != null
      ? { key: "Latencia LLM", value: fmtLatency(asNumber(metrics.llm_latency_ms)), mono: true }
      : null,
    asNumber(metrics.total_tokens) != null
      ? { key: "Tokens", value: fmtNum(asNumber(metrics.total_tokens)), mono: true }
      : null,
    cost != null ? { key: "Coste", value: fmtCurrency(cost, 4), mono: true } : null,
    asNumber(metrics.prompt_tokens) != null
      ? { key: "Tokens de prompt", value: fmtNum(asNumber(metrics.prompt_tokens)), mono: true }
      : null,
    asNumber(metrics.completion_tokens) != null
      ? {
          key: "Tokens de respuesta",
          value: fmtNum(asNumber(metrics.completion_tokens)),
          mono: true,
        }
      : null,
  ].filter((item): item is { key: string; value: string; mono: boolean } => item !== null);

  return (
    <div className="flex flex-col gap-5">
      <div className="flex flex-wrap items-center gap-2">
        <StatusBadge status={row.status || "completed"} />
        {caseScore(row) != null && <Badge tone="neutral">score {fmtScore(row.scores?.composite)}</Badge>}
        {asNumber(row.scores?.faithfulness) != null && (
          <Badge tone="neutral">fidelidad {fmtScore(row.scores?.faithfulness)}</Badge>
        )}
        {row.error && (
          <Badge tone="danger" icon={XCircle}>
            error del caso
          </Badge>
        )}
      </div>

      <div>
        <p className="eyebrow mb-1.5">Pregunta</p>
        <p className="text-[13.5px] leading-relaxed text-text">{row.question}</p>
      </div>

      {row.error && <ErrorInline message={row.error} className="mb-0" />}

      <div>
        <p className="eyebrow mb-1.5">Respuesta del run</p>
        {row.actual || row.answer ? (
          <p className="panel-quiet p-3 text-[13px] leading-relaxed whitespace-pre-wrap text-text">
            {row.actual || row.answer}
          </p>
        ) : (
          <p className="text-[13px] text-faint">El run no guardó respuesta para este caso.</p>
        )}
      </div>

      {(row.expected_answer || (row.expected_sources || []).length > 0) && (
        <div className="flex flex-col gap-3">
          {row.expected_answer && (
            <div>
              <p className="eyebrow mb-1.5">Respuesta esperada</p>
              <p className="text-[13px] leading-relaxed text-muted">{row.expected_answer}</p>
            </div>
          )}
          {(row.expected_sources || []).length > 0 && (
            <div>
              <p className="eyebrow mb-1.5">Fuentes esperadas</p>
              <ul className="flex flex-wrap gap-1.5">
                {(row.expected_sources || []).map((source) => (
                  <li
                    key={source}
                    className="chip mono max-w-full truncate"
                    title={source}
                  >
                    {source}
                  </li>
                ))}
              </ul>
            </div>
          )}
        </div>
      )}

      <div>
        <p className="eyebrow mb-1.5">
          Fragmentos recuperados {retrieved.length > 0 ? `(${retrieved.length})` : ""}
        </p>
        {retrieved.length === 0 ? (
          <p className="text-[13px] text-faint">
            El run no persistió fragmentos recuperados para este caso.
          </p>
        ) : (
          <ol className="flex flex-col gap-2">
            {retrieved.map((chunk, i) => (
              <li key={i} className="panel-quiet p-3">
                <div className="flex items-center justify-between gap-2">
                  <span className="eyebrow">Fragmento {i + 1}</span>
                  {asNumber(chunk.score) != null && (
                    <Badge tone="info">score {asNumber(chunk.score)?.toFixed(3)}</Badge>
                  )}
                </div>
                <p className="mt-2 text-[13px] leading-relaxed whitespace-pre-wrap text-muted">
                  {chunk.content || "Sin contenido."}
                </p>
              </li>
            ))}
          </ol>
        )}
      </div>

      {metricItems.length > 0 && (
        <div>
          <p className="eyebrow mb-2">Métricas del caso</p>
          <KeyValue items={metricItems} columns={2} />
        </div>
      )}
    </div>
  );
}

export default function EvaluationRunDetailPage() {
  const { runId } = useParams();
  const { session } = useAuth();
  const [data, setData] = useState<RunDetail | null>(null);
  const [failures, setFailures] = useState<Failure[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [evidence, setEvidence] = useState<Evidence | null>(null);
  const [sort, setSort] = useState<SortState>(null);

  useEffect(() => {
    if (!session || !runId) return;
    let cancelled = false;
    (async () => {
      setLoading(true);
      try {
        const detail = await api<RunDetail>(`/api/v1/eval/runs/${runId}`, {
          token: session.token,
          organizationId: session.organizationId,
        });
        const failuresOut = await api<{ failures: Failure[] }>(
          `/api/v1/eval/runs/${runId}/failures`,
          { token: session.token, organizationId: session.organizationId }
        );
        if (cancelled) return;
        setData(detail);
        setFailures(failuresOut.failures || []);
        setError("");
      } catch (err) {
        if (cancelled) return;
        setError(err instanceof Error ? err.message : "Error cargando el run");
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [session, runId]);

  const q = data?.quality || {};
  const composite = fmtScore(q.composite_score);
  const hallucination = asNumber(q.hallucination_rate);
  const judgeEnabled = q.judge_enabled === true;
  const judgeModel = typeof q.judge_model === "string" ? q.judge_model : "";
  const totalCases = data?.total_cases ?? data?.cases?.length ?? 0;
  const failedCases = data?.failed_cases ?? 0;

  const dimensionMetrics = QUALITY_METRICS.map((metric) => ({
    ...metric,
    value: asNumber(q[metric.key]),
  })).filter((metric) => metric.value != null);

  const performanceMetrics = useMemo(() => {
    if (!data) return [] as { key: string; label: string; value: string }[];
    const items: { key: string; label: string; value: string }[] = [];
    const avg = avgLatencyOf(data);
    const p50 = p50Of(data);
    const p95 = p95Of(data);
    const totalCost = asNumber(data.performance?.total_cost);
    const totalTokens = asNumber(data.performance?.total_tokens);
    if (avg != null) items.push({ key: "avg", label: "Latencia media", value: fmtLatency(avg) });
    if (p50 != null) items.push({ key: "p50", label: "Latencia p50", value: fmtLatency(p50) });
    if (p95 != null) items.push({ key: "p95", label: "Latencia p95", value: fmtLatency(p95) });
    if (totalTokens != null)
      items.push({ key: "tokens", label: "Tokens totales", value: fmtNum(totalTokens) });
    if (totalCost != null)
      items.push({ key: "cost", label: "Coste total", value: fmtCurrency(totalCost, 4) });
    return items;
  }, [data]);

  const sortedCases = useMemo(
    () => sortCases(data?.cases || [], sort),
    [data?.cases, sort]
  );

  const caseColumns: Column<CaseRow>[] = [
    {
      key: "question",
      header: "Pregunta",
      sortable: true,
      render: (row) => (
        <p className="max-w-[320px] truncate text-[13px] text-text" title={row.question}>
          {row.question}
        </p>
      ),
    },
    {
      key: "status",
      header: "Estado",
      hideBelow: "md",
      render: (row) => <StatusBadge status={row.status || "completed"} />,
    },
    {
      key: "composite",
      header: "Score",
      align: "right",
      sortable: true,
      render: (row) => (
        <span className="mono text-[13px]">
          {caseScore(row) == null ? "—" : caseScore(row)?.toFixed(3)}
        </span>
      ),
    },
    {
      key: "latency",
      header: "Latencia",
      align: "right",
      sortable: true,
      hideBelow: "md",
      render: (row) => (
        <span className="mono text-xs text-muted tabular-nums">
          {fmtLatency(caseLatency(row))}
        </span>
      ),
    },
    {
      key: "cost",
      header: "Coste",
      align: "right",
      sortable: true,
      hideBelow: "lg",
      render: (row) => (
        <span className="mono text-xs text-muted tabular-nums">
          {caseCost(row) == null ? "—" : fmtCurrency(caseCost(row), 4)}
        </span>
      ),
    },
  ];

  function openCaseById(caseId: string) {
    const row = (data?.cases || []).find((c) => c.case_id === caseId);
    if (row) {
      setEvidence({ kind: "case", row });
      return;
    }
    const failure = failures.find((f) => f.case_id === caseId);
    if (failure) setEvidence({ kind: "failure", row: failure });
  }

  return (
    <QualityLayout>
      <PageHeader
        title={data?.dataset_name || "Detalle del run"}
        subtitle="Solo se muestran métricas que el engine calculó. Nada inventado."
        breadcrumbs={[
          { label: "Evaluation", to: "/evaluation" },
          { label: "Runs", to: "/evaluation/runs" },
          { label: runId ? runId.slice(0, 8) : "Detalle" },
        ]}
        actions={
          <>
            <ButtonLink
              to="/evaluation/runs"
              variant="secondary"
              leadingIcon={ArrowLeft}
            >
              Volver a runs
            </ButtonLink>
            <ButtonLink
              to="/evaluation/compare"
              variant="secondary"
              leadingIcon={ArrowCounterClockwise}
            >
              Comparar
            </ButtonLink>
          </>
        }
      />

      <div className="flex flex-col gap-4">
        <ErrorInline message={error} className="mb-0" />

        {loading && !data && (
          <div className="flex flex-col gap-4" aria-busy="true">
            <Skeleton className="h-[124px] rounded-lg" />
            <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-4">
              {Array.from({ length: 4 }).map((_, i) => (
                <Skeleton key={i} className="h-[96px] rounded-lg" />
              ))}
            </div>
            <Skeleton className="h-[300px] rounded-lg" />
          </div>
        )}

        {data && (
          <>
            <Panel>
              <div className="flex flex-col gap-4 p-4 lg:flex-row lg:items-center lg:justify-between">
                <div className="min-w-0">
                  <p className="eyebrow">Score compuesto</p>
                  <div className="mt-2 flex flex-wrap items-baseline gap-x-3 gap-y-1">
                    <span className="stat-value">{composite ?? "—"}</span>
                    <span className="text-sm text-muted">de 1.00 · promedio del dataset</span>
                  </div>
                  <div className="mt-2 flex flex-wrap items-center gap-2 text-[13px]">
                    <span className="text-muted tabular-nums">
                      {fmtNum(totalCases)} casos evaluados
                    </span>
                    {failedCases > 0 && (
                      <Badge tone="warn" icon={WarningCircle}>
                        {fmtNum(failedCases)} con fallos
                      </Badge>
                    )}
                    {data.created_at && (
                      <span className="text-xs text-faint tabular-nums">
                        {fmtDateTime(data.created_at)}
                      </span>
                    )}
                  </div>
                  {composite == null && (
                    <p className="mt-2 text-xs text-faint">
                      El engine no calculó score compuesto para este run.
                    </p>
                  )}
                </div>
                <div className="flex shrink-0 flex-wrap items-center gap-2">
                  {hallucination != null && (
                    <Badge
                      tone={hallucination > 0 ? "danger" : "ok"}
                      icon={hallucination > 0 ? WarningCircle : CheckCircle}
                    >
                      Alucinación {(hallucination * 100).toFixed(0)}%
                    </Badge>
                  )}
                  <Badge
                    tone={judgeEnabled ? "info" : "neutral"}
                    icon={judgeEnabled ? Sparkle : XCircle}
                  >
                    {judgeEnabled
                      ? `Juez LLM${judgeModel ? ` · ${judgeModel}` : ""}`
                      : "Sin juez LLM"}
                  </Badge>
                </div>
              </div>
            </Panel>

            {(dimensionMetrics.length > 0 || performanceMetrics.length > 0) && (
              <MetricGrid cols={4}>
                {dimensionMetrics.map((metric) => (
                  <Metric
                    key={metric.key}
                    size="md"
                    label={metric.label}
                    value={metric.value?.toFixed(3) ?? "—"}
                    hint="0-1"
                  />
                ))}
                {performanceMetrics.map((metric) => (
                  <Metric
                    key={metric.key}
                    size="md"
                    label={metric.label}
                    value={metric.value}
                  />
                ))}
              </MetricGrid>
            )}

            {dimensionMetrics.length === 0 && performanceMetrics.length === 0 && (
              <InfoInline
                className="mb-0"
                message="El engine no calculó métricas para este run. Revisá los casos y sus fallos."
              />
            )}

            <Tabs defaultValue="cases">
              <TabsList>
                <TabsTrigger value="cases" icon={ListChecks}>
                  Casos ({fmtNum(totalCases)})
                </TabsTrigger>
                <TabsTrigger value="failures" icon={WarningCircle}>
                  Fallos ({fmtNum(failures.length)})
                </TabsTrigger>
              </TabsList>

              <TabsContent value="cases">
                <DataTable
                  columns={caseColumns}
                  rows={sortedCases}
                  rowKey={(row) => row.case_id}
                  caption="Resultados por caso"
                  stickyHeader
                  sort={sort}
                  onSortChange={setSort}
                  onRowClick={(row) => setEvidence({ kind: "case", row })}
                  rowActions={(row) => (
                    <IconButton
                      label={`Ver evidencia de ${row.case_id.slice(0, 8)}`}
                      icon={Binoculars}
                      iconSize={15}
                      onClick={() => setEvidence({ kind: "case", row })}
                    />
                  )}
                  empty={
                    <EmptyState
                      compact
                      icon={ListChecks}
                      title="Sin casos"
                      body="El run no persistió resultados por caso. Verificá que el engine haya guardado el detalle."
                    />
                  }
                />
              </TabsContent>

              <TabsContent value="failures">
                {failures.length === 0 ? (
                  <Panel>
                    <EmptyState
                      compact
                      icon={CheckCircle}
                      title="Sin fallos bajo los umbrales"
                      body="Ningún caso quedó por debajo de score 60 ni superó 0.3 de alucinación."
                    />
                  </Panel>
                ) : (
                  <ul className="flex flex-col gap-2">
                    {failures.map((failure, i) => (
                      <li
                        key={failure.case_id || i}
                        className="panel flex flex-col gap-3 p-4 sm:flex-row sm:items-start sm:justify-between"
                      >
                        <div className="min-w-0">
                          <p className="text-[13.5px] font-medium text-text">
                            {failure.question}
                          </p>
                          <ul className="mt-2 flex flex-col gap-1">
                            {failure.reasons.map((reason, j) => (
                              <li
                                key={j}
                                className="flex items-start gap-1.5 text-xs text-danger"
                              >
                                <WarningCircle size={13} aria-hidden className="mt-0.5 shrink-0" />
                                <span className="mono">{reason}</span>
                              </li>
                            ))}
                          </ul>
                          <div className="mt-2 flex flex-wrap items-center gap-2">
                            {failure.score != null && (
                              <Badge tone="neutral">score {failure.score.toFixed(2)}</Badge>
                            )}
                            {failure.hallucination_rate != null && (
                              <Badge
                                tone={failure.hallucination_rate > 0 ? "danger" : "ok"}
                                icon={failure.hallucination_rate > 0 ? WarningCircle : CheckCircle}
                              >
                                alucinación {failure.hallucination_rate.toFixed(2)}
                              </Badge>
                            )}
                          </div>
                        </div>
                        <Button
                          size="sm"
                          variant="secondary"
                          leadingIcon={Binoculars}
                          onClick={() => openCaseById(failure.case_id)}
                          className="shrink-0"
                        >
                          Ver evidencia
                        </Button>
                      </li>
                    ))}
                  </ul>
                )}
              </TabsContent>
            </Tabs>
          </>
        )}
      </div>

      <Drawer
        open={evidence !== null}
        onOpenChange={(open) => {
          if (!open) setEvidence(null);
        }}
        title="Evidencia del caso"
        description={evidence?.row.question}
        width={560}
      >
        {evidence && <EvidenceBody evidence={evidence} />}
      </Drawer>
    </QualityLayout>
  );
}
