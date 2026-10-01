// =============================================================================
// ExecutionStoryView — composición de la historia (§37, §56)
// =============================================================================
// Sirve para knowledge query, agent run, workflow run y Company Ask: las fases
// que no aplican simplemente no aparecen.
import { useState } from "react";
import type { ImpactLoad, QueryImpact } from "../MemoryImpact";
import type { ReplayResult } from "../ReplayCompare";
import { ReplayCompare } from "../ReplayCompare";
import type { ExecutionStory, StoryEvent } from "../executionStory";
import { parseTraceability } from "../experience";
import ExecutionTimeline from "./ExecutionTimeline";
import ExperienceStory from "./ExperienceStory";
import LearningSummary from "./LearningSummary";
import NarrativeSteps from "./NarrativeSteps";
import PerformanceStory from "./PerformanceStory";
import ReasoningStory from "./ReasoningStory";
import ResponseShapeCard from "./ResponseShapeCard";
import StorySummary from "./StorySummary";
import StoryHero from "./StoryHero";
import TechnicalTrace from "./TechnicalTrace";
import TraceabilityDiagnostics from "./TraceabilityDiagnostics";

export type StoryMode = "story" | "performance" | "technical";

const MODE_LABELS: Record<StoryMode, string> = {
  story: "Historia",
  performance: "Rendimiento",
  technical: "Técnico",
};

export function ExecutionStoryView({
  story,
  mode,
  onModeChange,
  impact,
  impactState,
  memoryHits = 0,
  replay,
  replayError,
  replayPending,
  onReplay,
  showReplay = false,
  sqlView,
}: {
  story: ExecutionStory;
  mode: StoryMode;
  onModeChange: (mode: StoryMode) => void;
  impact: QueryImpact | null;
  impactState: ImpactLoad;
  memoryHits?: number;
  replay: ReplayResult | null;
  replayError: string;
  replayPending: boolean;
  onReplay: () => void;
  showReplay?: boolean;
  sqlView?: React.ReactNode;
}) {
  // El detalle del razonamiento vive en razonamiento, planificación, contexto y
  // verificación (inferencia y completitud se prueban al final del análisis).
  const reasoningEvents = story.phases
    .filter((phase) =>
      ["context", "planning", "reasoning", "verification"].includes(phase.id),
    )
    .flatMap((phase) => phase.events);

  // El contrato canónico manda cuando existe: la vista explicada se deriva de
  // `flow.traceability`. Sin él, se conserva la historia legacy intacta.
  const traceability = parseTraceability(story.technical.raw?.traceability);
  const explained = Boolean(traceability) && mode === "story";

  return (
    <div className="flex flex-col gap-5">
      <div className="flex items-center gap-1" role="tablist" aria-label="Vista del flujo">
        {(Object.keys(MODE_LABELS) as StoryMode[]).map((value) => (
          <ModeTab key={value} active={mode === value} onClick={() => onModeChange(value)}>
            {MODE_LABELS[value]}
          </ModeTab>
        ))}
      </div>

      {explained && traceability ? (
        <ExperienceStory
          story={story}
          traceability={traceability}
          onOpenTechnical={() => onModeChange("technical")}
        />
      ) : (
        <>{story.executionNarrative ? <StoryHero story={story} /> : <StorySummary story={story} />}</>
      )}

      {mode === "story" && !explained ? (
        story.executionNarrative ? (
          <NarrativeSteps story={story} />
        ) : (
          <ExecutionTimeline story={story} />
        )
      ) : null}
      {mode === "performance" ? <PerformanceStory story={story} /> : null}
      {mode === "technical" ? (
        <>
          {traceability ? <TraceabilityDiagnostics traceability={traceability} /> : null}
          <KnowledgeRepresentation raw={story.technical.raw} />
          <TechnicalTrace story={story} />
        </>
      ) : null}

      {mode === "story" && !explained && story.response ? (
        <ResponseShapeCard story={story} expanded={false} />
      ) : null}

      {mode === "story" && !explained && !story.executionNarrative && reasoningEvents.some((event) => isReasoningCard(event)) ? (
        <ReasoningDetail events={reasoningEvents.filter((event) => isReasoningCard(event))} />
      ) : null}

      {sqlView}

      {/* §50: la memoria se muestra UNA vez, en la historia. */}
      {mode === "story" ? (
        <LearningSummary state={impactState} impact={impact} memoryHits={memoryHits} />
      ) : null}

      {showReplay ? (
        <section>
          <p className="eyebrow mb-2">Comparar con Zent actual</p>
          <ReplayCompare
            result={replay}
            error={replayError}
            pending={replayPending}
            onReplay={onReplay}
          />
        </section>
      ) : null}
    </div>
  );
}

function isReasoningCard(event: StoryEvent): boolean {
  return (
    event.kind === "reasoning_plan" ||
    event.kind === "scenario_parse" ||
    event.kind === "state_reconstruction" ||
    event.kind === "hypothesis_test" ||
    event.kind === "inference_verification" ||
    event.kind === "analysis_completion" ||
    event.kind === "company_context"
  );
}

function ReasoningDetail({ events }: { events: StoryEvent[] }) {
  const [open, setOpen] = useState(true);
  return (
    <section>
      <button
        type="button"
        className="mb-2 flex w-full items-center justify-between gap-2 text-left"
        onClick={() => setOpen((value) => !value)}
        aria-expanded={open}
      >
        <span className="eyebrow">Análisis del escenario</span>
        <span className="text-[11.5px] text-accent">{open ? "Ocultar" : "Mostrar"}</span>
      </button>
      {open ? (
        <div className="flex flex-col gap-2">
          {events.map((event) => (
            <div key={event.id} className="rounded-sm border border-border-soft px-2.5 py-2">
              <p className="text-[12.5px] font-medium text-text">{event.title}</p>
              <ReasoningStory event={event} />
            </div>
          ))}
        </div>
      ) : null}
    </section>
  );
}

function KnowledgeRepresentation({ raw }: { raw: Record<string, unknown> }) {
  const block = raw.knowledge_representation;
  if (!block || typeof block !== "object") return null;
  const item = block as Record<string, unknown>;
  const rows: Array<[string, unknown]> = [
    ["document_understanding", item.document_understanding],
    ["canonical_version", item.canonical_version],
    ["retrieval", item.retrieval],
    ["source profile used", item.source_profile_used ? "YES" : "NO"],
    ["semantic units", item.semantic_units ? "YES" : "NO"],
    ["exact literals", item.exact_literals ?? "—"],
    ["legacy chunks used", item.legacy_chunks_used ? "YES" : "NO"],
  ];
  return (
    <section className="rounded-md border border-border px-3 py-2 text-[12px]" aria-label="KNOWLEDGE REPRESENTATION">
      <h3 className="mb-1 text-[11px] font-medium tracking-wide text-muted">KNOWLEDGE REPRESENTATION</h3>
      <dl className="grid grid-cols-2 gap-x-3 gap-y-1">
        {rows.map(([label, value]) => (
          <div key={label} className="contents">
            <dt className="text-muted">{label}</dt>
            <dd className="text-text">{value == null || value === "" ? "—" : String(value)}</dd>
          </div>
        ))}
      </dl>
      {typeof item.warning === "string" && item.warning ? (
        <p className="mt-2 text-muted">{item.warning}</p>
      ) : null}
    </section>
  );
}

function ModeTab({
  active,
  onClick,
  children,
}: {
  active: boolean;
  onClick: () => void;
  children: React.ReactNode;
}) {
  return (
    <button
      type="button"
      role="tab"
      aria-selected={active}
      onClick={onClick}
      className={`rounded-sm px-2.5 py-1 text-[12px] ${
        active ? "bg-surface-strong text-text" : "text-muted hover:text-text"
      }`}
    >
      {children}
    </button>
  );
}

export default ExecutionStoryView;
