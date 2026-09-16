import {
  ArrowCounterClockwise,
  CheckCircle,
  Minus,
  Question,
  TrendDown,
  TrendUp,
  WarningCircle,
  XCircle,
  type Icon,
} from "@phosphor-icons/react";
import { useEffect, useState, type FormEvent } from "react";
import { useSearchParams } from "react-router-dom";
import { api } from "../../api";
import { useAuth } from "../../auth";
import {
  Badge,
  Button,
  DataTable,
  EmptyState,
  ErrorInline,
  Field,
  Metric,
  MetricGrid,
  PageHeader,
  Panel,
  Select,
  Skeleton,
  type Column,
  type Tone,
} from "../../components/ui";
import { QualityLayout } from "../../components/QualityLayout";
import { fmtCurrency, fmtDateTime } from "../../lib/format";

type Run = { id: string; dataset_name?: string; created_at?: string };
type Dimension = {
  dimension: string;
  metric: string;
  baseline: number | null;
  current: number | null;
  delta?: number | null;
  delta_pct?: number | null;
  delta_ms?: number | null;
  warn_at?: number;
  fail_at?: number;
  warn_at_pct?: number;
  fail_at_pct?: number;
  warn_at_ms?: number;
  fail_at_ms?: number;
  status: string;
};
type Report = {
  overall: string;
  classification: string;
  dimensions: Dimension[];
};

const DIMENSION_LABELS: Record<string, string> = {
  quality: "Calidad (score compuesto)",
  faithfulness: "Fidelidad a las fuentes",
  hallucination: "Alucinación",
  cost: "Coste medio por caso",
  latency: "Latencia p95",
};

/** Veredictos del engine de regresión (pass/warn/fail/unknown) → tono + icono + texto. */
const VERDICT: Record<string, { tint: Tone; label: string; Icon: Icon }> = {
  pass: { tint: "ok", label: "Aprueba", Icon: CheckCircle },
  warn: { tint: "warn", label: "Con avisos", Icon: WarningCircle },
  fail: { tint: "danger", label: "Falla", Icon: XCircle },
  unknown: { tint: "neutral", label: "Sin datos", Icon: Question },
};

const CLASSIFICATION: Record<
  string,
  { tint: Tone; label: string; Icon: Icon; body: string; panel: string }
> = {
  regression: {
    tint: "danger",
    label: "Regresión",
    Icon: TrendDown,
    body: "La versión nueva empeora frente al baseline. No promuevas sin revisar las dimensiones en falla.",
    panel: "border-danger/25 bg-danger-soft",
  },
  improvement: {
    tint: "ok",
    label: "Mejora",
    Icon: TrendUp,
    body: "La versión nueva mejora el score compuesto sin regresiones por encima de los umbrales.",
    panel: "border-ok/25 bg-ok-soft",
  },
  no_material_change: {
    tint: "neutral",
    label: "Sin cambio material",
    Icon: Minus,
    body: "Ninguna dimensión supera los umbrales de regresión. El resultado es equivalente al baseline.",
    panel: "border-border bg-raised",
  },
};

const SEVERITY_RANK: Record<string, number> = { fail: 0, warn: 1, unknown: 2, pass: 3 };

function fmtValue(metric: string, value: number | null | undefined): string {
  if (value == null || Number.isNaN(value)) return "—";
  if (metric === "avg_cost") return fmtCurrency(value, 4);
  if (metric === "p95_ms") return `${value.toFixed(0)} ms`;
  return value.toFixed(3);
}

function fmtDelta(dimension: Dimension): string {
  const pct = dimension.delta_pct;
  const abs = dimension.delta ?? dimension.delta_ms;
  if (pct != null && !Number.isNaN(pct)) return `${pct > 0 ? "+" : ""}${pct.toFixed(1)}%`;
  if (abs != null && !Number.isNaN(abs)) return `${abs > 0 ? "+" : ""}${abs.toFixed(3)}`;
  return "—";
}

function fmtThreshold(dimension: Dimension): string {
  if (dimension.dimension === "quality" || dimension.dimension === "faithfulness") {
    return dimension.fail_at == null ? "—" : `Δ ≤ ${dimension.fail_at.toFixed(3)}`;
  }
  if (dimension.dimension === "hallucination") {
    return dimension.fail_at == null ? "—" : `Δ ≥ +${dimension.fail_at}`;
  }
  if (dimension.dimension === "cost") {
    return dimension.fail_at_pct == null ? "—" : `Δ ≥ +${dimension.fail_at_pct}%`;
  }
  if (dimension.dimension === "latency") {
    const pct = dimension.fail_at_pct != null ? `+${dimension.fail_at_pct}%` : null;
    const ms = dimension.fail_at_ms != null ? `+${dimension.fail_at_ms} ms` : null;
    return [pct, ms].filter(Boolean).join(" o ") || "—";
  }
  return "—";
}

export default function EvaluationComparePage() {
  const { session } = useAuth();
  const [params] = useSearchParams();
  const [runs, setRuns] = useState<Run[]>([]);
  const [currentId, setCurrentId] = useState(params.get("current") || "");
  const [baselineId, setBaselineId] = useState("");
  const [report, setReport] = useState<Report | null>(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (!session) return;
    let cancelled = false;
    api<{ runs: Run[] }>("/api/v1/eval/runs?limit=100", {
      token: session.token,
      organizationId: session.organizationId,
    })
      .then((out) => {
        if (cancelled) return;
        setRuns(out.runs || []);
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
  }, [session]);

  async function onCompare(e: FormEvent) {
    e.preventDefault();
    if (!session || !currentId || !baselineId) return;
    setBusy(true);
    setError("");
    try {
      setReport(
        await api<Report>(`/api/v1/eval/runs/${currentId}/compare`, {
          method: "POST",
          token: session.token,
          organizationId: session.organizationId,
          body: JSON.stringify({ baseline_run_id: baselineId }),
        })
      );
    } catch (err) {
      setError(err instanceof Error ? err.message : "Compare falló");
    } finally {
      setBusy(false);
    }
  }

  const quality = report?.dimensions.find((d) => d.dimension === "quality");
  const regressions = report?.dimensions.filter((d) => d.status === "fail") ?? [];
  const sortedDimensions = [...(report?.dimensions ?? [])].sort(
    (a, b) =>
      (SEVERITY_RANK[a.status] ?? 3) - (SEVERITY_RANK[b.status] ?? 3) ||
      a.dimension.localeCompare(b.dimension)
  );
  const classification = report ? (CLASSIFICATION[report.classification] ?? CLASSIFICATION.no_material_change) : null;

  const columns: Column<Dimension>[] = [
    {
      key: "dimension",
      header: "Dimensión",
      render: (dim) => (
        <div className="min-w-0">
          <p className="text-[13.5px] font-medium text-text">
            {DIMENSION_LABELS[dim.dimension] ?? dim.dimension}
          </p>
          <p className="mono text-xs text-faint">{dim.metric}</p>
        </div>
      ),
    },
    {
      key: "baseline",
      header: "Baseline",
      align: "right",
      render: (dim) => (
        <span className="mono text-[13px] text-muted tabular-nums">
          {fmtValue(dim.metric, dim.baseline)}
        </span>
      ),
    },
    {
      key: "current",
      header: "Actual",
      align: "right",
      render: (dim) => (
        <span className="mono text-[13px] tabular-nums">{fmtValue(dim.metric, dim.current)}</span>
      ),
    },
    {
      key: "delta",
      header: "Δ",
      align: "right",
      render: (dim) => {
        const verdict = VERDICT[dim.status] ?? VERDICT.unknown;
        return (
          <span
            className={
              dim.status === "fail"
                ? "mono text-[13px] font-medium text-danger tabular-nums"
                : dim.status === "warn"
                  ? "mono text-[13px] font-medium text-warn tabular-nums"
                  : "mono text-[13px] text-muted tabular-nums"
            }
          >
            <verdict.Icon size={13} aria-hidden className="mr-1 inline-block align-[-2px]" />
            {fmtDelta(dim)}
          </span>
        );
      },
    },
    {
      key: "threshold",
      header: "Falla si",
      align: "right",
      hideBelow: "lg",
      render: (dim) => (
        <span className="mono text-xs text-faint tabular-nums">{fmtThreshold(dim)}</span>
      ),
    },
    {
      key: "status",
      header: "Veredicto",
      align: "right",
      render: (dim) => {
        const verdict = VERDICT[dim.status] ?? VERDICT.unknown;
        return (
          <Badge tone={verdict.tint} icon={verdict.Icon}>
            {verdict.label}
          </Badge>
        );
      },
    },
  ];

  return (
    <QualityLayout>
      <PageHeader
        title="Comparar runs"
        subtitle="Regresión contra un baseline. Veredictos del compare existente: pass / warn / fail."
      />

      <div className="flex flex-col gap-4">
        <ErrorInline message={error} className="mb-0" />

        <Panel>
          <form className="grid gap-4 p-4 sm:grid-cols-2" onSubmit={onCompare}>
            <Field label="Run actual" required>
              <Select
                id="cmp-current"
                value={currentId}
                onChange={(ev) => setCurrentId(ev.target.value)}
                placeholder="Selecciona…"
                required
              >
                {runs.map((run) => (
                  <option key={run.id} value={run.id}>
                    {(run.dataset_name || run.id.slice(0, 8)) +
                      (run.created_at ? ` · ${fmtDateTime(run.created_at)}` : "")}
                  </option>
                ))}
              </Select>
            </Field>
            <Field label="Baseline" required>
              <Select
                id="cmp-base"
                value={baselineId}
                onChange={(ev) => setBaselineId(ev.target.value)}
                placeholder="Selecciona…"
                required
              >
                {runs.map((run) => (
                  <option key={run.id} value={run.id}>
                    {(run.dataset_name || run.id.slice(0, 8)) +
                      (run.created_at ? ` · ${fmtDateTime(run.created_at)}` : "")}
                  </option>
                ))}
              </Select>
            </Field>
            <div className="flex flex-wrap items-center gap-3 sm:col-span-2">
              <Button
                type="submit"
                variant="primary"
                loading={busy}
                disabled={!currentId || !baselineId || currentId === baselineId}
                leadingIcon={ArrowCounterClockwise}
              >
                Comparar
              </Button>
              {currentId && baselineId && currentId === baselineId && (
                <span className="text-xs text-warn">
                  El run actual y el baseline deben ser distintos.
                </span>
              )}
            </div>
          </form>
        </Panel>

        {loading ? (
          <div className="flex flex-col gap-3" aria-busy="true">
            <Skeleton className="h-[96px] rounded-lg" />
            <Skeleton className="h-[240px] rounded-lg" />
          </div>
        ) : error && !report ? null : !report ? (
          <Panel>
            <EmptyState
              icon={ArrowCounterClockwise}
              title="Sin comparación todavía"
              body="Elegí el run actual y su baseline para ver el delta por dimensión, los umbrales y qué dimensión bloquea la promoción."
              hint="El veredicto sale del engine de regresión: nada se recalcula en el portal."
            />
          </Panel>
        ) : (
          <>
            {classification && (
              <div className={`rounded-lg border p-4 ${classification.panel}`}>
                <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
                  <div className="flex min-w-0 gap-3">
                    <span
                      className={`flex h-10 w-10 shrink-0 items-center justify-center rounded-md border ${
                        classification.tint === "danger"
                          ? "border-danger/25 text-danger"
                          : classification.tint === "ok"
                            ? "border-ok/25 text-ok"
                            : "border-border text-muted"
                      }`}
                      aria-hidden
                    >
                      <classification.Icon size={20} />
                    </span>
                    <div className="min-w-0">
                      <h2 className="text-h2">
                        {classification.label}
                        {regressions.length > 0 && (
                          <span className="ml-2 text-muted">
                            · {regressions.length}{" "}
                            {regressions.length === 1 ? "dimensión en falla" : "dimensiones en falla"}
                          </span>
                        )}
                      </h2>
                      <p className="prose-measure mt-1 text-[13px] leading-relaxed text-muted">
                        {classification.body}
                      </p>
                      {regressions.length > 0 && (
                        <p className="mt-1.5 inline-flex items-start gap-1.5 text-[13px] font-medium text-danger">
                          <XCircle size={14} className="mt-0.5 shrink-0" aria-hidden />
                          <span>
                            Dimensiones en falla:{" "}
                            {regressions
                              .map(
                                (dim) => DIMENSION_LABELS[dim.dimension] ?? dim.dimension
                              )
                              .join(", ")}
                            . Revisalas antes de promover.
                          </span>
                        </p>
                      )}
                    </div>
                  </div>
                  <Badge tone={VERDICT[report.overall]?.tint ?? "neutral"} icon={VERDICT[report.overall]?.Icon ?? Question} className="shrink-0">
                    {VERDICT[report.overall]?.label ?? report.overall}
                  </Badge>
                </div>
              </div>
            )}

            {quality && (
              <MetricGrid cols={3}>
                <Metric
                  size="md"
                  label="Score baseline"
                  value={fmtValue(quality.metric, quality.baseline)}
                />
                <Metric
                  size="md"
                  label="Score actual"
                  value={fmtValue(quality.metric, quality.current)}
                />
                <Metric
                  size="md"
                  label="Δ score"
                  value={fmtDelta(quality)}
                  tone={
                    quality.status === "fail"
                      ? "danger"
                      : quality.status === "warn"
                        ? "warn"
                        : quality.status === "pass"
                          ? "ok"
                          : "default"
                  }
                  hint={quality.status === "pass" ? "dentro del umbral" : undefined}
                />
              </MetricGrid>
            )}

            <DataTable
              columns={columns}
              rows={sortedDimensions}
              rowKey={(dim) => dim.dimension}
              caption="Comparación por dimensión"
              stickyHeader
            />
          </>
        )}

        {!loading && runs.length < 2 && (
          <p className="text-xs text-faint">
            Se necesitan al menos dos runs del mismo dataset para que la comparación sea significativa.
          </p>
        )}
      </div>
    </QualityLayout>
  );
}
