import { CaretDown, CaretUp, Crosshair, X } from "@phosphor-icons/react";
import { useMemo, type ReactNode } from "react";
import { SIMULATOR_HEIGHT, clampSimulatorHeight } from "../../lib/studioLayout";
import { nodeMeta, type WorkflowGraph } from "../../lib/workflowGraph";
import { IconButton, StatusBadge, Tabs, TabsContent, TabsList, TabsTrigger } from "../ui";
import type { RunDetail } from "../WorkflowRunInspector";
import { DataView } from "./DataView";
import { ResizeHandle } from "./ResizeHandle";

export type SimulatorState = "closed" | "collapsed" | "open";

const STEP_TONE: Record<string, string> = {
  succeeded: "bg-ok",
  simulated: "bg-info",
  failed: "bg-danger",
  denied: "bg-danger",
  skipped: "bg-faint",
  pending_approval: "bg-warn",
  paused: "bg-warn",
};

type TraceProps = {
  run: RunDetail | null;
  graph: WorkflowGraph | null;
  selectedNodeId: string | null;
  onPickNode: (nodeId: string) => void;
};

/** Resultados del último run ligados al lienzo: cada paso lleva a su nodo. */
export function RunTracePane({ run, graph, selectedNodeId, onPickNode }: TraceProps) {
  const labels = useMemo(
    () => new Map((graph?.nodes ?? []).map((n) => [n.id, n.label || nodeMeta(n.type).label])),
    [graph],
  );
  const steps = run?.steps ?? [];
  const failed = steps.filter((s) => s.status === "failed" || s.status === "denied");

  if (!run) {
    return (
      <div className="flex h-full items-center justify-center p-4 text-center text-[12px] text-faint" data-testid="wf-trace-empty">
        Ejecuta una prueba: aquí verás cada paso, sus errores y el contexto, enlazados a los nodos del lienzo.
      </div>
    );
  }

  const stepButton = (s: (typeof steps)[number], i: number) => {
    const id = s.node_id ?? "";
    const label = (id && labels.get(id)) || s.node_type || s.step_type;
    return (
      <li key={`${id}-${i}`}>
        <button
          type="button"
          disabled={!id}
          data-testid="wf-trace-step"
          data-node-id={id}
          aria-current={id && id === selectedNodeId ? "true" : undefined}
          className={`flex min-h-9 w-full cursor-pointer items-center gap-2 rounded-md px-2 text-left outline-none hover:bg-soft focus-visible:ring-2 focus-visible:ring-accent disabled:cursor-default ${
            id && id === selectedNodeId ? "bg-soft" : ""
          }`}
          onClick={() => id && onPickNode(id)}
        >
          <span className={`h-2 w-2 shrink-0 rounded-full ${STEP_TONE[s.status] ?? "bg-faint"}`} aria-hidden />
          <span className="min-w-0 flex-1">
            <span className="block truncate text-[12.5px] text-text">{label}</span>
            {s.error ? (
              <span className="block truncate text-[11px] text-danger">{s.error}</span>
            ) : (
              <span className="block truncate text-[11px] text-faint">{s.status}</span>
            )}
          </span>
          {s.duration_ms != null && <span className="shrink-0 text-[11px] tabular-nums text-faint">{s.duration_ms} ms</span>}
          {id && <Crosshair size={13} className="shrink-0 text-faint" aria-hidden />}
        </button>
      </li>
    );
  };

  return (
    <Tabs defaultValue={failed.length ? "errors" : "trace"} className="flex h-full min-h-0 flex-col">
      <TabsList className="mx-2 mt-1.5">
        <TabsTrigger value="trace" data-testid="wf-trace-tab-trace">
          Trazas · {steps.length}
        </TabsTrigger>
        <TabsTrigger value="errors" data-testid="wf-trace-tab-errors">
          Errores{failed.length ? ` · ${failed.length}` : ""}
        </TabsTrigger>
        <TabsTrigger value="context" data-testid="wf-trace-tab-context">
          Contexto
        </TabsTrigger>
        <TabsTrigger value="state" data-testid="wf-trace-tab-state">
          Estado
        </TabsTrigger>
      </TabsList>
      <TabsContent value="trace" className="mt-0 min-h-0 flex-1 overflow-y-auto p-1.5">
        <ol className="space-y-0.5" data-testid="wf-trace-list">
          {steps.map(stepButton)}
        </ol>
      </TabsContent>
      <TabsContent value="errors" className="mt-0 min-h-0 flex-1 overflow-y-auto p-1.5">
        {failed.length ? (
          <ol className="space-y-0.5">{failed.map(stepButton)}</ol>
        ) : (
          <p className="p-2 text-[12px] text-ok">Ningún paso falló en este run.</p>
        )}
      </TabsContent>
      <TabsContent value="context" className="mt-0 min-h-0 flex-1 overflow-y-auto p-2">
        <DataView data={run.context ?? null} testId="wf-trace-context" emptyHint="El run no expuso contexto." />
      </TabsContent>
      <TabsContent value="state" className="mt-0 min-h-0 flex-1 overflow-y-auto p-2">
        <dl className="grid grid-cols-2 gap-x-3 gap-y-2 text-[12px]" data-testid="wf-trace-state">
          <div>
            <dt className="eyebrow">Estado</dt>
            <dd className="mt-0.5">
              <StatusBadge status={run.status} />
            </dd>
          </div>
          <div>
            <dt className="eyebrow">Duración</dt>
            <dd className="mt-0.5 tabular-nums text-text">{run.duration_ms != null ? `${run.duration_ms} ms` : "—"}</dd>
          </div>
          <div>
            <dt className="eyebrow">Modo</dt>
            <dd className="mt-0.5 text-text">{run.simulated ? "Simulación" : run.effective_level || "Real"}</dd>
          </div>
          <div>
            <dt className="eyebrow">Run</dt>
            <dd className="mt-0.5 truncate font-mono text-[11px] text-muted">{run.id}</dd>
          </div>
          {run.error && (
            <div className="col-span-2">
              <dt className="eyebrow">Error</dt>
              <dd className="mt-0.5 text-danger">{run.error}</dd>
            </div>
          )}
        </dl>
      </TabsContent>
    </Tabs>
  );
}

type DockProps = {
  state: SimulatorState;
  onStateChange: (state: SimulatorState) => void;
  height: number;
  onHeightChange: (height: number) => void;
  /** Alto disponible para limitar el máximo (70 %). */
  availableHeight: number;
  run: RunDetail | null;
  title?: string;
  /** Panel de prueba (conversación, payload, resultados). Se mantiene montado al cerrar. */
  children: ReactNode;
  trace: ReactNode;
};

/**
 * Simulador acoplado bajo el lienzo: redimensionable, minimizable y sin
 * desmontar su contenido (la conversación y el borrador de prueba no se pierden).
 */
export function SimulatorDock({ state, onStateChange, height, onHeightChange, availableHeight, run, title = "Simulador", children, trace }: DockProps) {
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
        <div className="flex min-h-0 min-w-0 flex-[3] [&_[data-testid=wf-test-panel]]:rounded-none [&_[data-testid=wf-test-panel]]:border-0 [&_[data-testid=wf-test-panel]]:shadow-none">
          {children}
        </div>
        <div className="hidden min-h-0 w-[min(40%,420px)] shrink-0 border-l border-border md:block" data-testid="wf-trace">
          {trace}
        </div>
      </div>
    </section>
  );
}
