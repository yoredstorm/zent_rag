import { ChartLineUp } from "@phosphor-icons/react";
import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../../api";
import { useAuth } from "../../auth";
import {
  EmptyState,
  ErrorInline,
  PageHeader,
  SkeletonBlock,
  StatCard,
  StatusBadge,
} from "../../components/ui";
import { QualityLayout } from "../../components/QualityLayout";

type RunRow = {
  run_id: string;
  dataset_name?: string;
  status?: string;
  quality?: Record<string, number | boolean | string | null>;
  performance?: { latency?: { p95?: number }; avg_cost?: number };
  created_at?: string | null;
};

export default function EvaluationOverview() {
  const { session } = useAuth();
  const [runs, setRuns] = useState<RunRow[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  useEffect(() => {
    if (!session) return;
    api<{ runs: RunRow[] }>("/api/v1/eval/runs", {
      token: session.token,
      organizationId: session.organizationId,
    })
      .then((d) => setRuns(d.runs || []))
      .catch((e) => setError(e instanceof Error ? e.message : "Error"))
      .finally(() => setLoading(false));
  }, [session]);

  const completed = runs.filter((r) => r.status === "completed" || !r.status);
  const scores = completed
    .map((r) => r.quality?.composite_score)
    .filter((v): v is number => typeof v === "number");
  const avgScore = scores.length
    ? scores.reduce((a, b) => a + b, 0) / scores.length
    : null;
  const best = scores.length ? Math.max(...scores) : null;
  const last = completed[0];

  return (
    <QualityLayout>
      <PageHeader
        title="Evaluation"
        subtitle="Calidad de respuestas RAG y agentes: runs, métricas y regresiones."
      />
      {error && <ErrorInline>{error}</ErrorInline>}
      {loading ? (
        <SkeletonBlock className="h-40" />
      ) : (
        <>
          <div className="mb-6 grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-4">
            <StatCard label="Runs totales" value={runs.length} />
            <StatCard label="Score promedio" value={avgScore == null ? "—" : avgScore.toFixed(2)} />
            <StatCard label="Mejor score" value={best == null ? "—" : best.toFixed(2)} />
            <StatCard label="Último run" value={last?.run_id ? last.run_id.slice(0, 8) : "—"} />
          </div>
          {runs.length === 0 ? (
            <div className="panel">
              <EmptyState
                icon={ChartLineUp}
                title="Sin runs"
                body="Crea un dataset e inicia un run para ver métricas."
              />
            </div>
          ) : (
            <div className="panel overflow-x-auto">
              <table className="table">
                <thead>
                  <tr>
                    <th>Run</th>
                    <th>Dataset</th>
                    <th>Estado</th>
                    <th>Score</th>
                    <th>Hallucination</th>
                    <th>p95</th>
                  </tr>
                </thead>
                <tbody>
                  {runs.map((r) => (
                    <tr key={r.run_id}>
                      <td>
                        <Link
                          className="font-mono text-xs text-accent hover:underline"
                          to={`/evaluation/runs/${r.run_id}`}
                        >
                          {r.run_id.slice(0, 8)}
                        </Link>
                      </td>
                      <td className="text-sm">{r.dataset_name || "—"}</td>
                      <td>
                        <StatusBadge status={r.status || "completed"} />
                      </td>
                      <td className="text-sm">
                        {typeof r.quality?.composite_score === "number"
                          ? r.quality.composite_score.toFixed(2)
                          : "—"}
                      </td>
                      <td className="text-sm">
                        {typeof r.quality?.hallucination_rate === "number"
                          ? r.quality.hallucination_rate.toFixed(3)
                          : "—"}
                      </td>
                      <td className="text-sm">
                        {r.performance?.latency?.p95 != null
                          ? `${r.performance.latency.p95.toFixed(0)}ms`
                          : "—"}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </>
      )}
    </QualityLayout>
  );
}