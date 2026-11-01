import { Eye, Play, ShieldCheck, type Icon } from "@phosphor-icons/react";
import type { KeyboardEvent } from "react";
import { Badge } from "../ui";
import { LEVEL_DESCRIPTION, LEVEL_LABEL } from "./workflowTestPresentation";
import type { RealLane, TestLevel } from "./workflowTestTypes";

type UiMode = "preview" | "simulation" | "real";

const MODES: { id: UiMode; label: string; icon: Icon; level: TestLevel }[] = [
  { id: "preview", label: "Vista previa", icon: Eye, level: "preview" },
  { id: "simulation", label: "Simular", icon: Play, level: "simulation" },
  { id: "real", label: "Real", icon: ShieldCheck, level: "sandbox" },
];

function modeOfLevel(level: TestLevel): UiMode {
  return level === "preview" || level === "simulation" ? level : "real";
}

export function WorkflowTestModePicker({
  level,
  realLane,
  disabled,
  onSelectMode,
  onSelectRealLane,
}: {
  level: TestLevel;
  realLane: RealLane | null;
  disabled?: boolean;
  onSelectMode: (mode: UiMode) => void;
  onSelectRealLane: (lane: RealLane) => void;
}) {
  const current = modeOfLevel(level);

  function onKeyDown(event: KeyboardEvent<HTMLButtonElement>, index: number) {
    if (event.key !== "ArrowRight" && event.key !== "ArrowLeft") return;
    event.preventDefault();
    const next = event.key === "ArrowRight" ? (index + 1) % MODES.length : (index - 1 + MODES.length) % MODES.length;
    onSelectMode(MODES[next].id);
    const buttons = event.currentTarget.parentElement?.querySelectorAll<HTMLButtonElement>("[role=radio]");
    buttons?.[next]?.focus();
  }

  return (
    <section className="space-y-2" aria-labelledby="wf-mode-label">
      <div className="flex items-center justify-between gap-2">
        <p id="wf-mode-label" className="text-[13px] font-medium text-text">
          Modo de prueba
        </p>
        <Badge tone={current === "real" ? "warn" : "neutral"}>
          {current === "real" ? "Nivel real" : "Nivel seguro"}
        </Badge>
      </div>

      <div
        className="grid grid-cols-3 gap-1 rounded-md border border-border bg-soft p-0.5"
        role="radiogroup"
        aria-labelledby="wf-mode-label"
        data-testid="wf-test-levels"
      >
        {MODES.map((mode, index) => {
          const selected = current === mode.id;
          const Icon = mode.icon;
          return (
            <button
              key={mode.id}
              type="button"
              role="radio"
              aria-checked={selected}
              tabIndex={selected ? 0 : -1}
              disabled={disabled}
              className={`flex min-h-10 items-center justify-center gap-1 rounded-sm px-1.5 text-[12px] font-medium transition-colors duration-150 disabled:cursor-not-allowed disabled:opacity-50 ${
                selected ? "bg-surface text-text shadow-panel" : "text-muted hover:text-text"
              }`}
              data-testid={mode.id === "real" ? "wf-mode-real" : `wf-level-${mode.id}`}
              onClick={() => onSelectMode(mode.id)}
              onKeyDown={(event) => onKeyDown(event, index)}
            >
              <Icon size={13} weight={selected ? "fill" : "regular"} aria-hidden />
              {mode.label}
            </button>
          );
        })}
      </div>

      {current === "real" ? (
        <div className="space-y-2 rounded-md border border-warn/30 bg-warn-soft px-3 py-2.5" data-testid="wf-real-lane">
          <p className="text-[12px] font-medium text-text">Elige una operación real admitida</p>
          <div className="space-y-1.5" role="radiogroup" aria-label="Operación real admitida">
            <button
              type="button"
              role="radio"
              aria-checked={realLane === "sandbox"}
              className={`flex w-full items-start gap-2 rounded-sm border px-2.5 py-2 text-left transition-colors duration-150 ${
                realLane === "sandbox" ? "border-accent bg-surface text-text" : "border-border bg-raised/60 text-muted"
              }`}
              data-testid="wf-level-sandbox"
              onClick={() => onSelectRealLane("sandbox")}
            >
              <span className="mt-0.5 text-[13px]" aria-hidden>
                {realLane === "sandbox" ? "●" : "○"}
              </span>
              <span className="min-w-0">
                <span className="block text-[12.5px] font-medium">Probar en sandbox</span>
                <span className="mt-0.5 block text-[11.5px] leading-relaxed">
                  Solo si el backend tiene un sandbox conectado. No ejecuta el workflow productivo.
                </span>
              </span>
            </button>
            <button
              type="button"
              role="radio"
              aria-checked={realLane === "provider"}
              className={`flex w-full items-start gap-2 rounded-sm border px-2.5 py-2 text-left transition-colors duration-150 ${
                realLane === "provider" ? "border-accent bg-surface text-text" : "border-border bg-raised/60 text-muted"
              }`}
              data-testid="wf-level-provider"
              onClick={() => onSelectRealLane("provider")}
            >
              <span className="mt-0.5 text-[13px]" aria-hidden>
                {realLane === "provider" ? "●" : "○"}
              </span>
              <span className="min-w-0">
                <span className="block text-[12.5px] font-medium">Solicitar certificación con proveedor</span>
                <span className="mt-0.5 block text-[11.5px] leading-relaxed">
                  El servidor decide si puede. Si no hay adaptador, el reporte queda UNVERIFIED.
                </span>
              </span>
            </button>
          </div>
          <p className="text-[11.5px] leading-relaxed text-warn" data-testid="wf-level-unavailable">
            La disponibilidad no se deduce de esta pantalla. Se comprueba al ejecutar y el servidor
            informa el nivel efectivo.
          </p>
        </div>
      ) : (
        <p className="text-[12px] leading-relaxed text-muted" data-testid="wf-mode-description">
          {LEVEL_DESCRIPTION[current]}
        </p>
      )}

      {current === "real" && !realLane && (
        <p className="text-[11.5px] text-warn" role="status">
          Elige sandbox o proveedor para habilitar la prueba real.
        </p>
      )}

      <p className="sr-only">
        Nivel solicitado actual: {LEVEL_LABEL[level]}. {LEVEL_DESCRIPTION[level]}
      </p>
    </section>
  );
}
