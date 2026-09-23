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
  const metrics: Array<{ label: string; value: string }> = [
    { label: "Ruta", value: story.routeLabel },
    { label: "Resultado", value: story.outcomeLabel },
  ];
  if (story.confidenceLabel) metrics.push({ label: "Confianza", value: story.confidenceLabel });
  if (story.evidenceLabel) metrics.push({ label: "Evidencia", value: story.evidenceLabel });
  if (story.reasoningLabel) metrics.push({ label: "Razonamiento", value: story.reasoningLabel });
  metrics.push({ label: "Tiempo", value: fmtMs(story.totalMs) });
  if (story.costUsd !== null) metrics.push({ label: "Costo", value: fmtCurrency(story.costUsd, 6) });

  return (
    <div className="rounded-lg border border-border bg-surface p-4">
      <div className="flex flex-wrap items-center gap-2">
        <span className="text-h2">{story.headline}</span>
        <Badge tone={story.headlineStatus === "ok" ? "ok" : "warn"} dot>
          {story.headlineStatus === "ok" ? "Sin incidencias" : "Revisar"}
        </Badge>
        {story.legacy ? <Badge tone="neutral">Flujo histórico</Badge> : null}
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

      {story.breakdown.length > 1 ? (
        <div className="mt-4">
          <p className="text-[11.5px] text-faint">Distribución del tiempo</p>
          <ul className="mt-1.5 flex flex-col gap-1">
            {story.breakdown.map((row) => (
              <li
                key={row.label}
                className="flex items-center gap-2 text-[11.5px] text-muted"
              >
                <span className="w-40 shrink-0 truncate">{row.label}</span>
                <span
                  className="h-1.5 rounded-full bg-accent/60"
                  style={{
                    width: `${Math.max(2, Math.round((row.ms / Math.max(1, story.totalMs)) * 100))}%`,
                  }}
                  aria-hidden
                />
                <span className="mono ml-auto shrink-0 tabular-nums text-faint">
                  {fmtMs(row.ms)}
                  {row.costUsd !== null && row.costUsd > 0
                    ? ` · ${fmtCurrency(row.costUsd, 6)}`
                    : ""}
                </span>
              </li>
            ))}
          </ul>
        </div>
      ) : null}
    </div>
  );
}

export default StorySummary;
