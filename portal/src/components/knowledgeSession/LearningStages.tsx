// =============================================================================
// LearningStages — etapas humanas del aprendizaje (con detalle técnico)
// =============================================================================
// Leyendo / Entendiendo / Organizando / Conectando / Verificando / Aprendido.
// Debajo de cada etapa vive su nombre técnico (parser, semantic units, ...).
// =============================================================================
import { CheckCircle, Circle, CircleNotch } from "@phosphor-icons/react";

import type { SessionStage } from "../../lib/knowledgeSessions";
import { stageIndex } from "./stages";

export function LearningStages({
  stages,
  current,
  compact = false,
}: {
  stages: SessionStage[];
  current: string;
  compact?: boolean;
}) {
  const currentIndex = stageIndex(current);
  return (
    <ol
      className={`ks-stages ${compact ? "ks-stages-compact" : ""}`}
      data-testid="learning-stages"
      aria-label="Etapas del aprendizaje"
    >
      {stages.map((stage, index) => {
        const state =
          index < currentIndex
            ? "done"
            : index === currentIndex
              ? "current"
              : "pending";
        return (
          <li key={stage.key} className="ks-stage" data-state={state}>
            <span className="ks-stage-icon" aria-hidden>
              {state === "done" && (
                <CheckCircle size={17} weight="fill" className="text-ok" />
              )}
              {state === "current" && (
                <CircleNotch size={17} className="ks-spin text-accent" />
              )}
              {state === "pending" && (
                <Circle size={17} className="text-faint" />
              )}
            </span>
            <span className="ks-stage-text">
              <span className="ks-stage-label">{stage.label}</span>
              {!compact && stage.technical && (
                <span className="ks-stage-tech">{stage.technical}</span>
              )}
            </span>
          </li>
        );
      })}
    </ol>
  );
}

export default LearningStages;
