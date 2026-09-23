// =============================================================================
// ResponseShapeCard — "cómo explicó" la respuesta (§51-§54)
// =============================================================================
// Dato observable de composición: forma elegida, nivel, si pidió ejemplo o
// tabla, y si exigió citas. Nunca contenido, nunca razonamiento privado.
import type { ExecutionStory } from "../executionStory";
import { sectionLabel } from "../executionStory";

export function ResponseShapeCard({
  story,
  expanded = false,
}: {
  story: ExecutionStory;
  expanded?: boolean;
}) {
  const response = story.response;
  if (!response) return null;
  const flags: string[] = [];
  if (response.needsExample) flags.push("con ejemplo");
  if (response.needsTable) flags.push("con tabla");
  if (response.needsStepByStep) flags.push("paso a paso");
  if (response.citationsRequired) flags.push("con citas");
  if (response.hedgingRequired) flags.push("sin certeza definitiva");

  return (
    <section className="rounded-lg border border-border-soft px-3 py-2.5">
      <div className="flex flex-wrap items-baseline gap-x-2">
        <p className="eyebrow">Cómo lo explicó</p>
        <span className="text-[12.5px] text-text">{response.label}</span>
        <span className="text-[11.5px] text-faint">
          {response.detailLabel.toLowerCase()} · {response.decidedByLabel.toLowerCase()}
        </span>
      </div>
      {flags.length ? (
        <p className="mt-1 text-[11.5px] text-muted">{flags.join(" · ")}</p>
      ) : null}
      {expanded && response.sections.length ? (
        <div className="mt-2">
          <p className="text-[11.5px] text-faint">Orden sugerido</p>
          <ol className="mt-1 flex flex-wrap gap-x-3 gap-y-1 text-[11.5px] text-muted">
            {response.sections.map((section, index) => (
              <li key={section} className="flex items-center gap-1">
                <span className="mono text-faint">{index + 1}.</span>
                {sectionLabel(section)}
              </li>
            ))}
          </ol>
        </div>
      ) : null}
    </section>
  );
}

export default ResponseShapeCard;
