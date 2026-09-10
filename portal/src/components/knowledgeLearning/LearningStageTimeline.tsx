// =============================================================================
// LearningStageTimeline — etapas reales del run con timestamps
// =============================================================================
import { CheckCircle, Circle, WarningCircle } from "@phosphor-icons/react";
import type { LearningStep } from "../../lib/knowledgeLearning";
import { stageLabel } from "../../lib/knowledgeLearning";

function StepIcon({ status }: { status: LearningStep["status"] }) {
  if (status === "completed") {
    return <CheckCircle size={16} weight="fill" className="text-ok" aria-hidden />;
  }
  if (status === "failed") {
    return <WarningCircle size={16} weight="fill" className="text-danger" aria-hidden />;
  }
  if (status === "running") {
    return (
      <Circle
        size={16}
        weight="fill"
        className="animate-pulse-soft text-accent"
        aria-hidden
      />
    );
  }
  return <Circle size={16} className="text-faint" weight="regular" aria-hidden />;
}

export function LearningStageTimeline({
  steps,
  compact = false,
}: {
  steps: LearningStep[];
  compact?: boolean;
}) {
  return (
    <ol className="space-y-1.5" data-testid="learning-timeline">
      {steps.map((step) => (
        <li key={step.id} className="flex items-start gap-2">
          <span className="mt-0.5">
            <StepIcon status={step.status} />
          </span>
          <div className="min-w-0 flex-1">
            <div className="flex items-center justify-between gap-2">
              <span
                className={`truncate text-[13px] ${
                  step.status === "pending" ? "text-faint" : "text-text"
                }`}
              >
                {stageLabel(step.stage)}
              </span>
              {!compact && step.duration_ms > 0 && (
                <span className="shrink-0 font-mono text-[10px] text-faint">
                  {(step.duration_ms / 1000).toFixed(1)}s
                </span>
              )}
            </div>
            {step.error && (
              <p className="mt-0.5 text-[11px] text-danger">{step.error.slice(0, 160)}</p>
            )}
          </div>
        </li>
      ))}
    </ol>
  );
}
