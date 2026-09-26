// =============================================================================
// AgentStageNav — DESARROLLAR → PROBAR → PUBLICAR.
// =============================================================================
// Configurar el agente y operarlo son cosas distintas: publicar (versiones,
// entornos, embed, evaluación) no es un parámetro más del agente.
// =============================================================================
import { Flask, PaperPlaneRight, Sliders } from "@phosphor-icons/react";
import { AGENT_STAGES, AGENT_STAGE_LABELS, type AgentStage } from "./types";
import { cn } from "../ui";

const STAGE_ICONS: Record<AgentStage, typeof Sliders> = {
  develop: Sliders,
  test: Flask,
  publish: PaperPlaneRight,
};

const STAGE_HINTS: Record<AgentStage, string> = {
  develop: "Identidad, conocimiento, comportamiento e inteligencia.",
  test: "Conversá con el agente y mirá en qué se apoyó.",
  publish: "Versiones, entornos, widget, evaluación y reglas de calidad.",
};

export function AgentStageNav({
  stage,
  onStage,
  className,
}: {
  stage: AgentStage;
  onStage: (stage: AgentStage) => void;
  className?: string;
}) {
  return (
    <div
      className={cn("tabs", className)}
      role="tablist"
      aria-label="Etapas del agente"
    >
      {AGENT_STAGES.map((id) => {
        const Icon = STAGE_ICONS[id];
        return (
          <button
            key={id}
            type="button"
            role="tab"
            id={`agent-stage-${id}`}
            aria-selected={stage === id}
            aria-controls={`agent-stage-panel-${id}`}
            title={STAGE_HINTS[id]}
            className="tab"
            onClick={() => onStage(id)}
          >
            <Icon size={14} aria-hidden />
            {AGENT_STAGE_LABELS[id]}
          </button>
        );
      })}
    </div>
  );
}

export function AgentStagePanel({
  stage,
  children,
}: {
  stage: AgentStage;
  children: React.ReactNode;
}) {
  return (
    <div
      id={`agent-stage-panel-${stage}`}
      role="tabpanel"
      aria-labelledby={`agent-stage-${stage}`}
      tabIndex={-1}
    >
      {children}
    </div>
  );
}
