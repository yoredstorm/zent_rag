// =============================================================================
// LearningProgress — progreso real del backend (overall_progress/stage)
// =============================================================================
import { stageLabel } from "../../lib/knowledgeLearning";

export function LearningProgress({
  overallProgress,
  currentStage,
  stageProgress,
  status,
}: {
  overallProgress: number;
  currentStage: string;
  stageProgress?: number;
  status: string;
}) {
  const percent = Math.max(0, Math.min(100, Math.round(overallProgress || 0)));
  const failed = status === "failed";
  const waiting = status === "awaiting_validation";
  const fillClass = failed
    ? "bg-danger"
    : waiting
      ? "bg-warn"
      : "bg-accent";
  return (
    <div data-testid="learning-progress">
      <div className="flex items-baseline justify-between gap-3">
        <span className="text-sm text-muted">
          {failed
            ? "El aprendizaje falló"
            : waiting
              ? `Zent espera tu validación (${stageLabel(currentStage)})`
              : `${stageLabel(currentStage)}...`}
        </span>
        <span className="text-sm font-semibold tabular-nums text-text">
          {percent}%
        </span>
      </div>
      <div
        className="progress-track mt-2"
        role="progressbar"
        aria-valuenow={percent}
        aria-valuemin={0}
        aria-valuemax={100}
        aria-label="Progreso del aprendizaje"
      >
        <div
          className={`progress-fill ${fillClass}`}
          style={{ width: `${percent}%` }}
        />
      </div>
      {typeof stageProgress === "number" && stageProgress > 0 && stageProgress < 100 && (
        <p className="mt-1 text-[11px] text-faint">
          Etapa actual al {Math.round(stageProgress)}%
        </p>
      )}
    </div>
  );
}
