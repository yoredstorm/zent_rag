import { CaretDown, CaretUp, X } from "@phosphor-icons/react";
import { type ReactNode } from "react";
import { SIMULATOR_HEIGHT, clampSimulatorHeight } from "../../lib/studioLayout";
import { IconButton, StatusBadge } from "../ui";
import type { RunDetail } from "../WorkflowRunInspector";
import { ResizeHandle } from "./ResizeHandle";

export type SimulatorState = "closed" | "collapsed" | "open";

type DockProps = {
  state: SimulatorState;
  onStateChange: (state: SimulatorState) => void;
  height: number;
  onHeightChange: (height: number) => void;
  /** Alto disponible para limitar el máximo (70 %). */
  availableHeight: number;
  run: RunDetail | null;
  title?: string;
  /** Consola completa: entrada y resultado. Se mantiene montada al cerrar. */
  children: ReactNode;
};

/**
 * Simulador acoplado bajo el lienzo: redimensionable, minimizable y sin
 * desmontar su contenido (la conversación y el borrador de prueba no se pierden).
 */
export function SimulatorDock({ state, onStateChange, height, onHeightChange, availableHeight, run, title = "Simulador", children }: DockProps) {
  const failed = (run?.steps ?? []).filter((s) => s.status === "failed" || s.status === "denied").length;
  const max = clampSimulatorHeight(Number.POSITIVE_INFINITY, availableHeight);
  const current = clampSimulatorHeight(height, availableHeight);
  const open = state === "open";

  return (
    <section
      className={`relative shrink-0 flex-col border-t border-border bg-surface ${state === "closed" ? "hidden" : "flex"}`}
      style={open ? { height: current } : undefined}
      data-testid="wf-simulator"
      data-state={state}
      aria-label={title}
    >
      {open && (
        <ResizeHandle
          axis="y"
          value={current}
          min={SIMULATOR_HEIGHT.min}
          max={max}
          resetTo={SIMULATOR_HEIGHT.initial}
          onChange={onHeightChange}
          label="Alto del simulador"
          testId="wf-simulator-resize"
        />
      )}
      <header className="flex h-9 shrink-0 items-center gap-2 border-b border-border px-3">
        <button
          type="button"
          className="flex min-w-0 flex-1 cursor-pointer items-center gap-2 text-left outline-none focus-visible:ring-2 focus-visible:ring-accent"
          aria-expanded={open}
          onClick={() => onStateChange(open ? "collapsed" : "open")}
          data-testid="wf-simulator-toggle"
        >
          <span className="text-[13px] font-semibold text-text">{title}</span>
          {run && <StatusBadge status={run.status} />}
          {failed > 0 && <span className="text-[12px] text-danger">{failed} paso(s) con error</span>}
        </button>
        <IconButton
          label={open ? "Minimizar simulador" : "Expandir simulador"}
          icon={open ? CaretDown : CaretUp}
          className="h-7 w-7"
          iconSize={14}
          onClick={() => onStateChange(open ? "collapsed" : "open")}
          data-testid="wf-simulator-collapse"
        />
        <IconButton
          label="Cerrar simulador"
          icon={X}
          className="h-7 w-7"
          iconSize={14}
          onClick={() => onStateChange("closed")}
          data-testid="wf-simulator-close"
        />
      </header>
      <div className={`min-h-0 flex-1 ${open ? "flex" : "hidden"}`}>
        <div className="flex min-h-0 min-w-0 flex-1 [&_[data-testid=wf-test-panel]]:rounded-none [&_[data-testid=wf-test-panel]]:border-0 [&_[data-testid=wf-test-panel]]:shadow-none">
          {children}
        </div>
      </div>
    </section>
  );
}
