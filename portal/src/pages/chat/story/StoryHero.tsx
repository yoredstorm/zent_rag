import { Badge } from "../../../components/ui";
import { fmtCurrency } from "../../../lib/format";
import type { ExecutionStory } from "../executionStory";

function fmtMs(value: number): string {
  if (value <= 0) return "No disponible";
  if (value >= 1000) return `${(value / 1000).toFixed(1)} s`;
  return `${Math.round(value)} ms`;
}

export function StoryHero({ story }: { story: ExecutionStory }) {
  const narrative = story.executionNarrative;
  if (!narrative) return null;
  const influenced = narrative.summary.decisionsInfluenced;
  const jevValue = narrative.summary.judgmentCount
    ? influenced
      ? `${influenced} decisión${influenced === 1 ? "" : "es"} aplicada${influenced === 1 ? "" : "s"}`
      : "Revisó sin cambiar el camino"
    : "No fue necesario";
  const metrics = [
    { label: "Qué hizo", value: story.narrative },
    { label: "Fuentes", value: story.evidenceLabel || "No utilizó documentos" },
    { label: "Intervención JEV", value: jevValue },
    { label: "Tiempo", value: fmtMs(story.totalMs) },
    ...(story.costUsd === null
      ? []
      : [{ label: "Costo", value: fmtCurrency(story.costUsd, 6) }]),
  ];

  return (
    <header className="rounded-lg border border-border bg-surface p-4">
      <div className="flex flex-wrap items-center gap-2">
        <h2 className="text-h2 text-text">{story.headline}</h2>
        <Badge tone={story.headlineStatus === "ok" ? "ok" : "warn"}>
          {story.outcomeLabel}
        </Badge>
      </div>
      <dl className="mt-3 grid grid-cols-1 gap-x-4 gap-y-2 text-[12px] sm:grid-cols-2">
        {metrics.map((metric) => (
          <div key={metric.label} className={metric.label === "Qué hizo" ? "sm:col-span-2" : ""}>
            <dt className="text-faint">{metric.label}</dt>
            <dd className="text-text">{metric.value}</dd>
          </div>
        ))}
      </dl>
    </header>
  );
}

export default StoryHero;
