import { TrendUp } from "@phosphor-icons/react";
import { useCallback, useEffect, useState } from "react";
import { api } from "../../api";
import { useAuth } from "../../auth";
import { ErrorInline, PageHeader, SkeletonBlock } from "../../components/ui";
import { QualityLayout } from "../../components/QualityLayout";

type Trends = {
  days: number;
  total_queries: number;
  answerability_rate: number;
  unsupported_question_rate: number;
  context_gaps_open: number;
  context_gaps_resolved: number;
  gap_resolution_rate: number;
  improvements_open: number;
  most_impactful_missing_concepts: { title: string; affected_queries: number }[];
  knowledge_approvals_30d: number;
  evaluation_replays: { total: number; pass: number; fail: number; unknown: number };
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
      .then(setTrends)
      .catch((e) => setError(String(e)))
      .finally(() => setLoading(false));
  }, [session]);

  useEffect(() => load(), [load]);

  return (
    <QualityLayout>
      <PageHeader
        title="Impacto del aprendizaje"
        subtitle="Métricas reales del ciclo gobernado (nada inventado)."
      />
      {error && <ErrorInline message={error} />}
      {loading || !trends ? (
        <SkeletonBlock rows={4} />
      ) : (
        <div className="space-y-3">
          <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
            {[
              ["Answerability", `${trends.answerability_rate}%`],
              ["No soportadas", `${trends.unsupported_question_rate}%`],
              ["Resolución de gaps", `${trends.gap_resolution_rate}%`],
              ["Aprobaciones 30d", String(trends.knowledge_approvals_30d)],
              ["Gaps abiertos", String(trends.context_gaps_open)],
              ["Mejoras abiertas", String(trends.improvements_open)],
              ["Replays", String(trends.evaluation_replays.total)],
              ["Replays pass", String(trends.evaluation_replays.pass)],
            ].map(([label, value]) => (
              <div key={label} className="card p-3">
                <div className="text-xs text-zinc-400">{label}</div>
                <div className="text-lg font-semibold">{value}</div>
              </div>
            ))}
          </div>

          {trends.most_impactful_missing_concepts.length > 0 && (
            <div className="card p-4">
              <div className="mb-2 flex items-center gap-2 font-medium">
                <TrendUp size={16} /> Conceptos faltantes más impactantes
              </div>
              <div className="space-y-1">
                {trends.most_impactful_missing_concepts.map((c) => (
                  <div key={c.title} className="flex justify-between text-sm">
                    <span>{c.title}</span>
                    <span className="text-zinc-400">{c.affected_queries} consultas</span>
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>
      )}
    </QualityLayout>
  );
}