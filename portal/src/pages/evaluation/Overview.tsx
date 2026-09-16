import {
  ArrowClockwise,
  ArrowsClockwise,
  ChartBar,
  ChartLineUp,
  CheckCircle,
  Stack,
  Trophy,
  WarningCircle,
} from "@phosphor-icons/react";
import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../../api";
import { useAuth } from "../../auth";
import {
  Badge,
  Button,
  ButtonLink,
  DataTable,
  EmptyState,
  Metric,
  MetricGrid,
  PageHeader,
  Pagination,
  Panel,
  ResultCount,
  StatusBadge,
  ToolbarSpacer,
  type Column,
  type SortState,
} from "../../components/ui";
import { QualityLayout } from "../../components/QualityLayout";
import { fmtDateTime, fmtLatency, fmtNum } from "../../lib/format";

type RunRow = {
  id: string;
  dataset_name?: string | null;
  target_type?: string;
  target_name?: string;
  status?: string;
  composite_score?: number | null;
  avg_latency_ms?: number | null;
  avg_cost?: number | null;
  created_at?: string | null;
};

const PAGE_SIZE = 10;

/** Score 0-1 con 3 decimales; null honesto si el engine no lo calculó. */
function fmtScore(value: number | null | undefined): string | null {
  if (typeof value !== "number" || Number.isNaN(value)) return null;
  return value.toFixed(3);
}

function sortRuns(rows: RunRow[], sort: SortState): RunRow[] {
  if (!sort) return rows;
  const dir = sort.dir === "asc" ? 1 : -1;
  return [...rows].sort((a, b) => {
    const av = a[sort.key as keyof RunRow];
    const bv = b[sort.key as keyof RunRow];
    if (av == null && bv == null) return 0;
    if (av == null) return 1;
    if (bv == null) return -1;
    if (typeof av === "number" && typeof bv === "number") return (av - bv) * dir;
    return String(av).localeCompare(String(bv), "es") * dir;
  });
}

export default function EvaluationOverview() {
  const { session } = useAuth();
  const [runs, setRuns] = useState<RunRow[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [reloadKey, setReloadKey] = useState(0);
  const [sort, setSort] = useState<SortState>(null);
  const [page, setPage] = useState(1);

  useEffect(() => {
    if (!session) return;
    let cancelled = false;
    setLoading(true);
    api<{ runs: RunRow[] }>("/api/v1/eval/runs?limit=100", {
      token: session.token,
      organizationId: session.organizationId,
    })
      .then((data) => {
        if (cancelled) return;
        setRuns(data.runs || []);
        setError("");
      })
      .catch((err: unknown) => {
        if (cancelled) return;
        setError(err instanceof Error ? err.message : "Error cargando runs");
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [session, reloadKey]);

  const completed = runs.filter((r) => r.status === "completed" || !r.status);
  const scores = completed
    .map((r) => r.composite_score)
    .filter((value): value is number => typeof value === "number");
  const avgScore = scores.length ? scores.reduce((a, b) => a + b, 0) / scores.length : null;
  const best = scores.length ? Math.max(...scores) : null;
  const withFailures = runs.filter((r) => r.status === "partial" || r.status === "failed").length;
  const latest = runs[0];
  const sorted = sortRuns(runs, sort);
  const totalPages = Math.max(1, Math.ceil(sorted.length / PAGE_SIZE));
  const safePage = Math.min(page, totalPages);
  const pageRows = sorted.slice((safePage - 1) * PAGE_SIZE, safePage * PAGE_SIZE);
  const capped = runs.length >= 100;

  const columns: Column<RunRow>[] = [
    {
      key: "dataset_name",
      header: "Run",
      sortable: true,
      render: (run) => (
        <div className="min-w-0">
          <Link
            to={`/evaluation/runs/${run.id}`}
            className="mono text-xs text-accent transition-colors duration-150 hover:underline"
          >
            {run.id.slice(0, 8)}
          </Link>
          <p className="mt-0.5 truncate text-[13px] text-text" title={run.dataset_name || undefined}>
            {run.dataset_name || "dataset sin nombre"}
          </p>
        </div>
      ),
    },
    {
      key: "status",
      header: "Estado",
      sortable: true,
      hideBelow: "md",
      render: (run) => <StatusBadge status={run.status || "completed"} />,
    },
    {
      key: "composite_score",
      header: "Score",
      align: "right",
      sortable: true,
      render: (run) => (
        <span className="mono text-[13px]">{fmtScore(run.composite_score) ?? "—"}</span>
      ),
    },
    {
      key: "avg_latency_ms",
      header: "Latencia media",
      align: "right",
      sortable: true,
      hideBelow: "md",
      render: (run) => (
        <span className="mono text-xs text-muted tabular-nums">
          {fmtLatency(run.avg_latency_ms ?? null)}
        </span>
      ),
    },
    {
      key: "created_at",
      header: "Fecha",
      sortable: true,
      hideBelow: "lg",
      render: (run) => (
        <span className="text-xs text-muted tabular-nums">{fmtDateTime(run.created_at)}</span>
      ),
    },
  ];

  return (
    <QualityLayout>
      <PageHeader
        title="Evaluation"
        subtitle="Calidad de respuestas RAG y agentes: runs, métricas y regresiones."
      />

      <div className="flex flex-col gap-4">
        {loading ? (
          <div className="flex flex-col gap-4" aria-busy="true">
            <div className="h-[124px] rounded-lg skeleton" />
            <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-4">
              {Array.from({ length: 4 }).map((_, i) => (
                <div key={i} className="h-[96px] rounded-lg skeleton" />
              ))}
            </div>
            <div className="h-[280px] rounded-lg skeleton" />
          </div>
        ) : error && runs.length === 0 ? (
          <Panel>
            <EmptyState
              icon={WarningCircle}
              title="No pudimos cargar los runs"
              body={error}
              hint="Revisá la conexión e intentá de nuevo."
              action={
                <Button
                  variant="primary"
                  leadingIcon={ArrowClockwise}
                  onClick={() => setReloadKey((key) => key + 1)}
                >
                  Reintentar
                </Button>
              }
            />
          </Panel>
        ) : runs.length === 0 ? (
          <Panel>
            <EmptyState
              icon={Stack}
              title="Sin runs"
              body="Importá un dataset e iniciá una evaluación para ver métricas por dimensión."
              hint="Cada run guarda score compuesto, latencia y coste por caso."
              action={
                <ButtonLink to="/evaluation/datasets" variant="primary">
                  Ir a datasets
                </ButtonLink>
              }
              secondaryAction={
                <ButtonLink to="/evaluation/runs" variant="secondary">
                  Lanzar run
                </ButtonLink>
              }
            />
          </Panel>
        ) : (
          <>
            {latest && (
              <Panel>
                <div className="flex flex-col gap-4 p-4 lg:flex-row lg:items-center lg:justify-between">
                  <div className="min-w-0">
                    <p className="eyebrow">Score del período</p>
                    <div className="mt-2 flex flex-wrap items-baseline gap-x-3 gap-y-1">
                      <span className="stat-value">{avgScore == null ? "—" : avgScore.toFixed(3)}</span>
                      <span className="text-sm text-muted">
                        {scores.length > 0
                          ? `promedio de ${fmtNum(scores.length)} ${scores.length === 1 ? "run con score" : "runs con score"}`
                          : "sin scores calculados"}
                      </span>
                    </div>
                    <div className="mt-2 flex flex-wrap items-center gap-2 text-[13px]">
                      {withFailures > 0 ? (
                        <Badge tone="warn" icon={WarningCircle}>
                          {fmtNum(withFailures)}{" "}
                          {withFailures === 1 ? "run parcial o fallido" : "runs parciales o fallidos"}
                        </Badge>
                      ) : (
                        <span className="inline-flex items-center gap-1.5 text-ok">
                          <CheckCircle size={15} weight="fill" aria-hidden />
                          Sin runs parciales ni fallidos
                        </span>
                      )}
                      <span className="text-muted">
                        {capped ? "últimos 100 runs" : `${fmtNum(runs.length)} runs`}
                      </span>
                    </div>
                    {avgScore == null && (
                      <p className="mt-2 text-xs text-faint">
                        Ningún run completado calculó score compuesto todavía. Revisá los casos en el
                        detalle o lanzá una evaluación con juez LLM.
                      </p>
                    )}
                  </div>
                  <div className="flex shrink-0 flex-col items-start gap-2.5 lg:items-end">
                    <div className="flex flex-wrap items-center gap-2">
                      <StatusBadge status={latest.status || "completed"} />
                      <span className="min-w-0 truncate text-[13px] text-muted">
                        último run · {latest.dataset_name || "dataset sin nombre"}
                      </span>
                      {latest.created_at && (
                        <span className="text-xs text-faint tabular-nums">
                          {fmtDateTime(latest.created_at)}
                        </span>
                      )}
                    </div>
                    <div className="flex flex-wrap items-center gap-2">
                      <ButtonLink to={`/evaluation/runs/${latest.id}`} variant="primary">
                        Ver último run
                      </ButtonLink>
                      <ButtonLink to="/evaluation/compare" variant="secondary">
                        Comparar
                      </ButtonLink>
                    </div>
                  </div>
                </div>
              </Panel>
            )}

            <MetricGrid cols={4}>
              <Metric
                size="md"
                label="Runs"
                value={fmtNum(runs.length)}
                icon={ChartBar}
                hint={capped ? "se listan los últimos 100" : undefined}
              />
              <Metric
                size="md"
                label="Con score"
                value={fmtNum(scores.length)}
                icon={ChartLineUp}
                hint="runs completados con score compuesto"
              />
              <Metric
                size="md"
                label="Mejor score"
                value={best == null ? "—" : best.toFixed(3)}
                icon={Trophy}
                hint={best == null ? "sin scores calculados" : undefined}
              />
              <Metric
                size="md"
                label="Runs con fallos"
                value={fmtNum(withFailures)}
                icon={WarningCircle}
                tone={withFailures > 0 ? "warn" : "default"}
                hint={withFailures > 0 ? "casos fallidos o parciales" : "sin casos fallidos"}
              />
            </MetricGrid>

            <DataTable
              columns={columns}
              rows={pageRows}
              rowKey={(run) => run.id}
              caption="Runs de evaluación"
              error={error}
              stickyHeader
              sort={sort}
              onSortChange={(next) => {
                setSort(next);
                setPage(1);
              }}
              toolbar={
                <>
                  <ResultCount shown={pageRows.length} total={runs.length} noun="runs" />
                  <ToolbarSpacer />
                  <Button
                    size="sm"
                    variant="ghost"
                    leadingIcon={ArrowsClockwise}
                    onClick={() => setReloadKey((key) => key + 1)}
                  >
                    Actualizar
                  </Button>
                </>
              }
              footer={
                sorted.length > PAGE_SIZE ? (
                  <Pagination
                    page={safePage}
                    pageSize={PAGE_SIZE}
                    total={sorted.length}
                    onPageChange={setPage}
                  />
                ) : undefined
              }
            />
          </>
        )}
      </div>
    </QualityLayout>
  );
}
