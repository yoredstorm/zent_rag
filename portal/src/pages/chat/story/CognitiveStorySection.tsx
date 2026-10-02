// =============================================================================
// CognitiveStorySection — nivel normal: cómo razonó el runtime cognitivo (C6).
// =============================================================================
import { Badge } from "../../../components/ui";
import { COGNITIVE_STEP_LABELS, parseCognitiveStory } from "../cognitiveStory";

export function CognitiveStorySection({ raw }: { raw?: Record<string, unknown> }) {
  const story = parseCognitiveStory(raw?.cognitive_story);
  if (!story || !story.normal.length) return null;
  const runId = String(story.raw.run_id ?? "");
  return (
    <section aria-label="Cómo razonó Zent">
      <div className="mb-2 flex items-center gap-2">
        <span className="eyebrow">Cómo razonó Zent</span>
        {runId ? <Badge tone="neutral">run {runId.slice(0, 8)}</Badge> : null}
      </div>
      <ol className="flex flex-col gap-2">
        {story.normal.map((step, index) => {
          const meta = COGNITIVE_STEP_LABELS[step.kind];
          if (!meta) return null;
          return (
            <li
              key={`${step.kind}-${index}`}
              className="flex gap-3 rounded-md border border-border-soft px-3 py-2"
            >
              <span className="mt-0.5 flex h-5 w-5 shrink-0 items-center justify-center rounded-full bg-surface-strong text-[11px] text-muted">
                {index + 1}
              </span>
              <div>
                <p className="text-[12.5px] font-medium text-text">{meta.title}</p>
                <p className="text-[12px] text-muted">{meta.body(step.metrics)}</p>
              </div>
            </li>
          );
        })}
      </ol>
    </section>
  );
}

export default CognitiveStorySection;
