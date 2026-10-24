import type { ParameterLevel } from "../../lib/businessSchema";
import { LEVEL_LABELS } from "../../lib/businessSchema";

const MODES: ParameterLevel[] = ["simple", "guided", "advanced"];

type Props = {
  value: ParameterLevel;
  onChange: (mode: ParameterLevel) => void;
};

/** Simple / Guiado / Avanzado: un solo workspace, distinta profundidad. */
export function ModeSwitch({ value, onChange }: Props) {
  return (
    <div
      className="flex flex-wrap gap-1"
      role="group"
      aria-label="Modo del Solution Workspace"
      data-testid="solution-mode-switch"
    >
      {MODES.map((mode) => (
        <button
          key={mode}
          type="button"
          aria-pressed={value === mode}
          className="min-h-8 rounded-md border border-border px-2.5 text-xs text-muted aria-pressed:border-accent aria-pressed:text-text"
          data-testid={`solution-mode-${mode}`}
          onClick={() => onChange(mode)}
        >
          {LEVEL_LABELS[mode]}
        </button>
      ))}
    </div>
  );
}
