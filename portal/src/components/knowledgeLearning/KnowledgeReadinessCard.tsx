// =============================================================================
// KnowledgeReadinessCard — score real con composición y razones (sección 11)
// =============================================================================
import { GATE_LABELS, gateTone, type KnowledgeScore } from "../../lib/knowledgeLearning";

function barTone(score: number): string {
  if (score >= 80) return "bg-ok";
  if (score >= 55) return "bg-accent";
  if (score >= 35) return "bg-warn";
  return "bg-danger";
}

export function KnowledgeReadinessCard({
  score,
  loading = false,
}: {
  score: KnowledgeScore | null;
  loading?: boolean;
}) {
  if (loading && !score) {
    return (
      <section className="panel" data-testid="readiness-card">
        <h2 className="text-sm font-semibold text-text">Knowledge Readiness</h2>
        <p className="mt-2 text-[13px] text-faint">Calculando…</p>
      </section>
    );
  }
  if (!score) {
    return (
      <section className="panel" data-testid="readiness-card">
        <h2 className="text-sm font-semibold text-text">Knowledge Readiness</h2>
        <p className="mt-2 text-[13px] text-faint">
          Aún no hay un score calculado. Inicia un aprendizaje para construirlo.
        </p>
      </section>
    );
  }
  const overall = Math.round(score.overall || 0);
  return (
    <section className="panel" data-testid="readiness-card">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h2 className="text-sm font-semibold text-text">Knowledge Readiness</h2>
          <p className="mt-0.5 text-[12px] text-muted">
            Mide entendimiento validado, no cantidad de embeddings.
          </p>
        </div>
        <div className="flex items-center gap-2">
          <span className="text-3xl font-semibold tabular-nums text-text">{overall}%</span>
          <span className={`badge ${gateTone(score.gate)}`}>
            {GATE_LABELS[score.gate] ?? score.gate}
          </span>
        </div>
      </div>
      <div className="progress-track mt-3">
        <div
          className={`progress-fill ${barTone(overall)}`}
          style={{ width: `${Math.max(0, Math.min(100, overall))}%` }}
        />
      </div>
      <ul className="mt-4 space-y-2.5" data-testid="score-dimensions">
        {score.dimensions.map((dimension) => (
          <li key={dimension.key}>
            <div className="flex items-center justify-between gap-2 text-[12px]">
              <span className="text-text">
                {dimension.label}
                <span className="ml-1 text-faint">
                  {Math.round(dimension.weight * 100)}%
                </span>
              </span>
              <span className="tabular-nums text-muted">
                {dimension.measured ? `${Math.round(dimension.score)}%` : "sin medir"}
              </span>
            </div>
            <div className="progress-track mt-1 h-1">
              <div
                className={`h-full rounded-full ${barTone(dimension.score)}`}
                style={{
                  width: `${dimension.measured ? Math.max(0, Math.min(100, dimension.score)) : 0}%`,
                }}
              />
            </div>
            {dimension.detail && (
              <p className="mt-0.5 text-[11px] text-faint">{dimension.detail}</p>
            )}
          </li>
        ))}
      </ul>
      {score.reasons.length > 0 && (
        <div className="mt-4 rounded-md border border-border bg-soft/40 p-3">
          <p className="text-[12px] font-medium text-text">¿Por qué no es mayor?</p>
          <ul className="mt-1.5 list-disc space-y-1 pl-4 text-[12px] text-muted">
            {score.reasons.map((reason) => (
              <li key={reason}>{reason}</li>
            ))}
          </ul>
        </div>
      )}
    </section>
  );
}
