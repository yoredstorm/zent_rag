import { useEffect, useState } from "react";
import { useParams } from "react-router-dom";
import { api } from "../../api";
import { useAuth } from "../../auth";
import { ErrorInline, PageHeader, SkeletonBlock, StatCard } from "../../components/ui";
import { QualityLayout } from "../../components/QualityLayout";

type CaseRow = {
  case_id: string;
  question: string;
  expected_sources?: string[];
  expected_answer?: string | null;
  retrieved?: { content?: string }[];
  actual?: string;
  answer?: string;
  scores?: { composite?: number };
  latency_ms?: number;
  cost?: number;
  metrics?: { latency_ms?: number; cost?: number };
};

type RunDetail = {
  run_id: string;
  dataset_name?: string;
  quality?: Record<string, number | boolean | string | null>;
  performance?: {
    latency?: { p50?: number; p95?: number };
    total_cost?: number;
    avg_cost?: number;
  };
  cases?: CaseRow[];
};

function num(value: unknown): string {
  if (typeof value !== "number" || Number.isNaN(value)) return "—";
  return value.toFixed(3);
}

export default function EvaluationRunDetailPage() {
  const { runId } = useParams();
  const { session } = useAuth();
  const [data, setData] = useState<RunDetail | null>(null);
  const [failures, setFailures] = useState<{ case_id: string; question: string; answer: string | null; score: number | null; hallucination_rate: number | null; reasons: string[] }[]>([]);
  const [showFailures, setShowFailures] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    if (!session || !runId) return;
    (async () => {
      try {
        setData(
          await api<RunDetail>(`/api/v1/eval/runs/${runId}`, {
            token: session.token,
            organizationId: session.organizationId,
          })
        );
        const f = await api<{ failures: { case_id: string; question: string; answer: string | null; score: number | null; hallucination_rate: number | null; reasons: string[] }[] }>(
          `/api/v1/eval/runs/${runId}/failures`,
          { token: session.token, organizationId: session.organizationId }
        );
        setFailures(f.failures || []);
        setError("");
      } catch (err) {
        setError(err instanceof Error ? err.message : "Error cargando el run");
      }
    })();
  }, [session, runId]);

  const q = data?.quality || {};
  const metricCards: { label: string; key: string }[] = [
    { label: "Score compuesto", key: "composite_score" },
    { label: "Retrieval precision", key: "retrieval_precision" },
    { label: "Retrieval recall", key: "retrieval_recall" },
    { label: "Faithfulness", key: "faithfulness" },
    { label: "Hallucination rate", key: "hallucination_rate" },
  ];

  return (
    <QualityLayout>
      <PageHeader
        title={data?.dataset_name || "Detalle del run"}
        subtitle="Solo se muestran métricas que el engine calculó. Nada inventado."
      />
      <ErrorInline message={error} />
      {!data && !error && <SkeletonBlock rows={6} />}
      {data && (
        <>          <div className="panel mb-6">
            <button
              type="button"
              className="btn btn-ghost min-h-9 text-xs"
              onClick={() => setShowFailures((v) => !v)}
            >
              {showFailures ? "Ocultar" : "Ver"} fallos ({failures.length})
            </button>
            {showFailures && (
              <div className="mt-3">
                {failures.length === 0 ? (
                  <p className="text-sm text-muted">Sin casos bajo los thresholds (score &lt; 60, hallucination &gt; 0.3).</p>
                ) : (
                  <ul className="space-y-3">
                    {failures.map((f, i) => (
                      <li key={f.case_id || i} className="rounded-md border border-border bg-soft p-3">
                        <p className="text-sm font-medium text-text">{f.question}</p>
                        {f.reasons.map((r, j) => (
                          <p key={j} className="mt-1 text-xs text-danger">{r}</p>
                        ))}
                        {f.answer && (
                          <details className="mt-2">
                            <summary className="cursor-pointer text-xs text-accent">Respuesta del run</summary>
                            <p className="mt-1 whitespace-pre-wrap text-xs text-muted">{f.answer}</p>
                          </details>
                        )}
                      </li>
                    ))}
                  </ul>
                )}
              </div>
            )}
          </div>
          <div className="mb-6 grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3">
            {metricCards.map((card) => (
              <StatCard key={card.key} label={card.label} value={num(q[card.key])} />
            ))}
            <StatCard
              label="Latencia p95"
              value={
                data.performance?.latency?.p95 == null
                  ? "—"
                  : `${data.performance.latency.p95.toFixed(0)} ms`
              }
            />
            <StatCard
              label="Coste total"
              value={
                data.performance?.total_cost == null
                  ? "—"
                  : `$${data.performance.total_cost.toFixed(4)}`
              }
            />
          </div>
          <div className="-mx-4 overflow-x-auto px-4 sm:mx-0 sm:px-0">
            <table className="w-full min-w-[960px] text-left text-sm">
              <thead>
                <tr className="border-b border-border text-xs uppercase tracking-wide text-faint">
                  <th className="py-2 pr-3 font-medium">Pregunta</th>
                  <th className="py-2 pr-3 font-medium">Esperado</th>
                  <th className="py-2 pr-3 font-medium">Retrieved</th>
                  <th className="py-2 pr-3 font-medium">Actual</th>
                  <th className="py-2 pr-3 font-medium">Score</th>
                  <th className="py-2 pr-3 font-medium">Latencia</th>
                  <th className="py-2 font-medium">Coste</th>
                </tr>
              </thead>
              <tbody>
                {(data.cases || []).map((row) => {
                  const expected =
                    row.expected_answer ||
                    (row.expected_sources || []).join(", ") ||
                    "—";
                  const retrieved = (row.retrieved || [])
                    .map((c) => (c.content || "").slice(0, 80))
                    .filter(Boolean)
                    .join(" · ");
                  const latency = row.latency_ms ?? row.metrics?.latency_ms;
                  const cost = row.cost ?? row.metrics?.cost;
                  return (
                    <tr key={row.case_id} className="border-b border-border/70 align-top">
                      <td className="max-w-[220px] py-3 pr-3">{row.question}</td>
                      <td className="max-w-[180px] py-3 pr-3 text-muted">{expected}</td>
                      <td className="max-w-[200px] py-3 pr-3 text-muted">
                        {retrieved || "—"}
                      </td>
                      <td className="max-w-[220px] py-3 pr-3">
                        {(row.actual || row.answer || "—").slice(0, 160)}
                      </td>
                      <td className="py-3 pr-3">
                        {row.scores?.composite == null
                          ? "—"
                          : row.scores.composite.toFixed(3)}
                      </td>
                      <td className="py-3 pr-3">
                        {latency == null ? "—" : `${Number(latency).toFixed(0)} ms`}
                      </td>
                      <td className="py-3">
                        {cost == null ? "—" : `$${Number(cost).toFixed(4)}`}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </>
      )}
    </QualityLayout>
  );
}
