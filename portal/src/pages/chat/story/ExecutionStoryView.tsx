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
import ExecutionTimeline from "./ExecutionTimeline";
import LearningSummary from "./LearningSummary";
import ReasoningStory from "./ReasoningStory";
import StorySummary from "./StorySummary";
import TechnicalTrace from "./TechnicalTrace";

export type StoryMode = "story" | "technical";

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

  return (
    <div className="flex flex-col gap-5">
      <div className="flex items-center gap-1" role="tablist" aria-label="Vista del flujo">
        <ModeTab active={mode === "story"} onClick={() => onModeChange("story")}>
          Historia
        </ModeTab>
        <ModeTab active={mode === "technical"} onClick={() => onModeChange("technical")}>
          Técnico
        </ModeTab>
      </div>

      <StorySummary story={story} />

      {mode === "story" ? (
        <ExecutionTimeline story={story} />
      ) : (
        <TechnicalTrace story={story} />
      )}

      {reasoningEvents.some((event) => isReasoningCard(event)) ? (
        <ReasoningDetail events={reasoningEvents.filter((event) => isReasoningCard(event))} />
      ) : null}

      {sqlView}

      <section>
        <p className="eyebrow mb-2">Memoria</p>
        <LearningSummary state={impactState} impact={impact} memoryHits={memoryHits} />
      </section>

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
