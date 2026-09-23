// =============================================================================
// ExecutionTimeline — la vista principal, vertical y progresiva (§30, §31, §46)
// =============================================================================
// Cada fase es una etapa numerada con estado, subtítulo y, al abrirla, sus
// eventos. Los incidentes (fallbacks, bloqueos) viven dentro de su etapa, no en
// una lista aparte sin contexto.
import { useState } from "react";
import { Badge, type Tone } from "../../../components/ui";
import {
  eventReasonsText,
  statusLabel,
  type ExecutionStory,
  type StoryEvent,
  type StoryStatus,
} from "../executionStory";
import { StoryCard } from "./StoryCards";

function statusTone(status: StoryStatus): Tone {
  if (status === "ok") return "ok";
  if (status === "warn") return "warn";
  if (status === "error") return "danger";
  return "neutral";
}

function statusGlyph(status: StoryStatus): string {
  // Nunca sólo color: icono + texto (§20, §53).
  if (status === "ok") return "✓";
  if (status === "warn") return "⚠";
  if (status === "error") return "✕";
  if (status === "skipped") return "–";
  return "○";
}

export function ExecutionTimeline({ story }: { story: ExecutionStory }) {
  const [open, setOpen] = useState<Record<string, boolean>>({});
  const [showTechnical, setShowTechnical] = useState(false);

  return (
    <div>
      <div className="mb-2 flex items-center justify-between gap-2">
        <p className="eyebrow">Cómo llegó Zent a esta respuesta</p>
        <button
          type="button"
          className="text-[11.5px] text-accent hover:underline"
          onClick={() => setShowTechnical((value) => !value)}
          aria-pressed={showTechnical}
        >
          {showTechnical ? "Ocultar detalle técnico" : "Mostrar detalle técnico"}
        </button>
      </div>
      <ol className="flex flex-col">
        {story.phases.map((phase, index) => (
          <li key={phase.id} className="flex gap-3">
            <div className="flex flex-col items-center pt-0.5">
              <span
                className="flex h-6 w-6 shrink-0 items-center justify-center rounded-full border border-border text-[11px] text-muted"
                aria-hidden
              >
                {statusGlyph(phase.status)}
              </span>
              {index < story.phases.length - 1 ? (
                <span className="w-px flex-1 bg-border" aria-hidden />
              ) : null}
            </div>
            <div className="min-w-0 flex-1 pb-4">
              <button
                type="button"
                className="w-full text-left"
                onClick={() =>
                  setOpen((current) => ({ ...current, [phase.id]: !current[phase.id] }))
                }
                aria-expanded={Boolean(open[phase.id])}
              >
                <span className="flex flex-wrap items-center gap-2">
                  <span className="text-[13px] font-medium text-text">
                    {`${index + 1}. ${phase.title}`}
                  </span>
                  <Badge tone={statusTone(phase.status)}>{statusLabel(phase.status)}</Badge>
                  {phase.durationMs > 0 ? (
                    <span className="mono text-[11px] tabular-nums text-faint">
                      {Math.round(phase.durationMs)} ms
                    </span>
                  ) : null}
                </span>
                {phase.subtitle ? (
                  <span className="mt-0.5 block text-[12px] text-muted">{phase.subtitle}</span>
                ) : null}
              </button>
              {open[phase.id] ? (
                <div className="mt-2 flex flex-col gap-2">
                  {phase.events.map((event) => (
                    <FlowEventRow key={event.id} event={event} detailed={showTechnical} />
                  ))}
                </div>
              ) : null}
            </div>
          </li>
        ))}
        {story.phases.length === 0 ? (
          <li className="text-[12.5px] text-muted">
            No hay pasos registrados para esta respuesta.
          </li>
        ) : null}
      </ol>

      {story.incidents.length ? (
        <p className="mt-1 text-[11.5px] text-muted">
          Incidencias: <span className="mono text-text">{story.incidents.length}</span>
        </p>
      ) : null}
    </div>
  );
}

function FlowEventRow({ event, detailed }: { event: StoryEvent; detailed: boolean }) {
  const reasons = eventReasonsText(event);
  return (
    <div className="rounded-sm border border-border-soft px-2.5 py-2" data-state={event.status}>
      <div className="flex flex-wrap items-center gap-2 text-[12.5px]">
        <span className={`text-[11px] ${event.status === "ok" ? "text-ok" : "text-warn"}`} aria-hidden>
          {statusGlyph(event.status)}
        </span>
        <span className="min-w-0 flex-1 font-medium text-text">{event.title}</span>
        {event.durationMs ? (
          <span className="mono text-[11px] tabular-nums text-faint">
            {Math.round(event.durationMs)} ms
          </span>
        ) : null}
      </div>
      {reasons ? <p className="mt-1 text-[11.5px] text-muted">Falta: {reasons}</p> : null}
      <StoryCard event={event} detailed={detailed} />
    </div>
  );
}

export default ExecutionTimeline;
