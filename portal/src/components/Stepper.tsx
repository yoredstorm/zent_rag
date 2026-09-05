export type StepDef = { id: string; label: string };

/**
 * Stepper de etapas con flujo visual (FASE 04).
 * Las etapas pasadas se marcan como completadas.
 */
export function Stepper({
  steps,
  active,
  onSelect,
}: {
  steps: StepDef[];
  active: string;
  onSelect: (id: string) => void;
}) {
  const activeIndex = steps.findIndex((s) => s.id === active);
  return (
    <ol className="mb-4 flex flex-wrap items-center gap-1" aria-label="Etapas">
      {steps.map((step, i) => {
        const isActive = step.id === active;
        const done = i < activeIndex;
        return (
          <li key={step.id} className="flex items-center">
            <button
              type="button"
              onClick={() => onSelect(step.id)}
              aria-current={isActive ? "step" : undefined}
              className={`flex items-center gap-1.5 rounded-md px-2.5 py-1.5 text-[13px] transition-colors duration-150 ${
                isActive
                  ? "bg-accent-soft font-medium text-accent"
                  : "text-muted hover:bg-soft hover:text-text"
              }`}
            >
              <span
                className={`flex h-5 w-5 items-center justify-center rounded-full text-[11px] font-semibold ${
                  isActive ? "bg-accent text-accent-fg" : done ? "bg-ok-soft text-ok" : "bg-soft text-faint"
                }`}
                aria-hidden
              >
                {i + 1}
              </span>
              {step.label}
            </button>
            {i < steps.length - 1 && <span className="mx-1 text-faint" aria-hidden>↓</span>}
          </li>
        );
      })}
    </ol>
  );
}