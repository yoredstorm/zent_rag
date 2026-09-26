// =============================================================================
// AgentSettingGroup — el patrón Auto / Personalizado del Agent Studio.
// =============================================================================
// Un grupo nunca arranca mostrando campos técnicos: muestra su estado en una
// línea y el detalle aparece sólo cuando el usuario pide personalizar. "Auto" es
// una decisión de UX: el valor guardado sigue siendo exactamente el mismo.
// =============================================================================
import { ArrowUUpLeft, CaretDown } from "@phosphor-icons/react";
import type { ReactNode } from "react";
import { Badge, Button, cn } from "../ui";

export type SettingMode = "auto" | "custom";

export type ModeOption = {
  value: string;
  label: string;
  hint?: string;
};

/**
 * Elección entre "recomendado" y "personalizado". Es un radiogroup real: flechas
 * para moverse, `aria-checked` por opción, y el estado nunca se comunica sólo
 * por color.
 */
export function AgentModeChoice({
  name,
  value,
  options,
  onChange,
  disabled = false,
  className,
}: {
  name: string;
  value: string;
  options: ModeOption[];
  onChange: (value: string) => void;
  disabled?: boolean;
  className?: string;
}) {
  function onKeyDown(event: React.KeyboardEvent, index: number) {
    if (event.key !== "ArrowRight" && event.key !== "ArrowDown" && event.key !== "ArrowLeft" && event.key !== "ArrowUp") {
      return;
    }
    event.preventDefault();
    const step = event.key === "ArrowRight" || event.key === "ArrowDown" ? 1 : -1;
    const next = options[(index + step + options.length) % options.length];
    onChange(next.value);
  }

  return (
    <div
      role="radiogroup"
      aria-label={name}
      className={cn("grid gap-1.5", options.length > 2 ? "" : "sm:grid-cols-2", className)}
    >
      {options.map((option, index) => {
        const selected = option.value === value;
        return (
          <button
            key={option.value}
            type="button"
            role="radio"
            aria-checked={selected}
            tabIndex={selected ? 0 : -1}
            disabled={disabled}
            onClick={() => onChange(option.value)}
            onKeyDown={(event) => onKeyDown(event, index)}
            className={cn(
              "flex cursor-pointer items-start gap-2.5 rounded-md border bg-raised p-2.5 text-left",
              "transition-colors duration-150",
              disabled && "pointer-events-none opacity-45",
              selected ? "border-accent-line bg-accent-soft/40" : "border-border hover:border-border-strong",
            )}
          >
            <span
              aria-hidden
              className={cn(
                "mt-0.5 inline-flex h-3.5 w-3.5 shrink-0 items-center justify-center rounded-full border transition-colors duration-150",
                selected ? "border-accent bg-accent" : "border-border-strong",
              )}
            >
              {selected && <span className="h-1.5 w-1.5 rounded-full bg-accent-fg" />}
            </span>
            <span className="min-w-0">
              <span className="block text-[13px] font-medium text-text">{option.label}</span>
              {option.hint && (
                <span className="mt-0.5 block text-xs leading-relaxed text-muted">{option.hint}</span>
              )}
            </span>
          </button>
        );
      })}
    </div>
  );
}

/**
 * Grupo de configuración con estado resumido. Cerrado se lee de un vistazo;
 * abierto muestra los campos técnicos y la opción de volver a lo recomendado.
 */
export function AgentSettingGroup({
  id,
  title,
  hint,
  mode,
  summary,
  onMode,
  open,
  onOpenChange,
  onRestore,
  restoreLabel = "Restaurar valores recomendados",
  autoLabel = "Automático",
  customLabel = "Personalizado",
  autoHint,
  customHint,
  children,
}: {
  id: string;
  title: string;
  hint?: string;
  mode: SettingMode;
  summary: string;
  onMode?: (mode: SettingMode) => void;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onRestore?: () => void;
  restoreLabel?: string;
  autoLabel?: string;
  customLabel?: string;
  autoHint?: string;
  customHint?: string;
  children: ReactNode;
}) {
  const detailId = `${id}-detail`;
  return (
    <section className="grid gap-3" data-testid={`agent-group-${id}`}>
      <div className="flex flex-wrap items-start justify-between gap-x-3 gap-y-1">
        <div className="min-w-0">
          <h4 className="flex flex-wrap items-center gap-2 text-[13px] font-semibold tracking-[-0.01em] text-text">
            {title}
            <Badge tone={mode === "auto" ? "accent" : "neutral"}>
              {mode === "auto" ? autoLabel : customLabel}
            </Badge>
          </h4>
          <p className="mt-0.5 text-xs leading-relaxed text-muted" data-testid={`agent-group-${id}-summary`}>
            {summary}
          </p>
          {hint && <p className="mt-0.5 text-xs leading-relaxed text-faint">{hint}</p>}
        </div>
        <button
          type="button"
          className="flex shrink-0 cursor-pointer items-center gap-1.5 rounded-sm px-1.5 py-1 text-[12.5px] font-medium text-accent transition-colors hover:text-accent-strong"
          aria-expanded={open}
          aria-controls={detailId}
          onClick={() => onOpenChange(!open)}
        >
          {open ? "Ocultar" : "Personalizar"}
          <CaretDown
            size={13}
            aria-hidden
            className={cn("transition-transform duration-200", open && "rotate-180")}
          />
        </button>
      </div>

      {open && (
        <div id={detailId} className="grid gap-4">
          {onMode && (
            <AgentModeChoice
              name={title}
              value={mode}
              options={[
                { value: "auto", label: autoLabel, hint: autoHint },
                { value: "custom", label: customLabel, hint: customHint },
              ]}
              onChange={(next) => onMode(next as SettingMode)}
            />
          )}
          <div className="animate-rise grid gap-4">{children}</div>
          {onRestore && (
            <div>
              <Button variant="secondary" size="sm" leadingIcon={ArrowUUpLeft} onClick={onRestore}>
                {restoreLabel}
              </Button>
            </div>
          )}
        </div>
      )}
    </section>
  );
}
