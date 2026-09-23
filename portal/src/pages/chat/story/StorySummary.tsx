// =============================================================================
// StorySummary — la tarjeta superior de la Execution Story (§29, §44)
// =============================================================================
import { Badge } from "../../../components/ui";
import { fmtCurrency } from "../../../lib/format";
import type { ExecutionStory } from "../executionStory";
import { JevImpactCard, JudgmentUncertaintyNote } from "./JudgmentStory";

function fmtMs(value: number): string {
  if (value <= 0) return "—";
  if (value >= 1000) return `${(value / 1000).toFixed(2)} s`;
  return `${value.toFixed(0)} ms`;
}

export function StorySummary({ story }: { story: ExecutionStory }) {
  // §23: las métricas se llaman por su semántica. "Confianza" sólo aparece si
  // existe una confianza real (nunca un 0 inventado).
  const metrics: Array<{ label: string; value: string }> = [
    { label: "Ruta", value: story.routeLabel },
    { label: "Resultado", value: story.outcomeLabel },
  ];
  if (story.evidenceLabel) metrics.push({ label: "Evidencia", value: story.evidenceLabel });
  if (story.reasoningLabel) metrics.push({ label: "Análisis", value: story.reasoningLabel });
  // §51: la forma de explicar es parte del resumen, en lenguaje humano.
  if (story.response) metrics.push({ label: "Explicación", value: story.response.label });
  if (story.confidenceLabel) {
    metrics.push({ label: "Confianza de ruta", value: story.confidenceLabel });
  }
  metrics.push({ label: "Tiempo", value: fmtMs(story.totalMs) });
  if (story.costUsd !== null) metrics.push({ label: "Costo", value: fmtCurrency(story.costUsd, 6) });

  return (
    <div className="rounded-lg border border-border bg-surface p-4">
      <div className="flex flex-wrap items-center gap-2">
        <span className="text-h2">{story.headline}</span>
        <Badge tone={story.headlineStatus === "ok" ? "ok" : "warn"} dot>
          {story.headlineStatus === "ok" ? "Sin incidencias" : "Revisar"}
        </Badge>
        {/* §46: la calidad del dato se declara, no se disfraza con "Revisar". */}
        <Badge tone={story.telemetry.qualityTone === "ok" ? "ok" : "neutral"}>
          {story.telemetry.qualityLabel}
        </Badge>
        {story.counts.unmapped > 0 ? (
          <Badge tone="warn">
            {story.counts.unmapped} evento{story.counts.unmapped === 1 ? "" : "s"} sin mapping
          </Badge>
        ) : null}
      </div>
      <p className="mt-1 text-[12.5px] text-muted">{story.narrative}</p>

      <dl className="mt-3 grid grid-cols-2 gap-x-4 gap-y-2 text-[12px] sm:grid-cols-3">
        {metrics.map((metric) => (
          <div key={metric.label} className="min-w-0">
            <dt className="text-faint">{metric.label}</dt>
            <dd className="truncate text-text">{metric.value}</dd>
          </div>
        ))}
      </dl>

      {story.jevImpact ? (
        <div className="mt-4 flex flex-col gap-2">
          <JevImpactCard impact={story.jevImpact} />
          <JudgmentUncertaintyNote impact={story.jevImpact} />
        </div>
      ) : null}
    </div>
  );
}

export default StorySummary;
