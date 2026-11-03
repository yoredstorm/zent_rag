import { WorkflowRunInspector, type RunDetail } from "../WorkflowRunInspector";
import type { RunOut } from "./workflowTestTypes";

export function WorkflowTestTrace({
  run,
  plannedEffects,
  onSelectNode,
}: {
  run: RunDetail | null;
  plannedEffects?: RunOut["planned_effects"];
  onSelectNode: (id: string) => void;
}) {
  if (!run) {
    return (
      <p className="rounded-md border border-border bg-raised/40 px-3 py-2 text-[12px] text-muted">
        Todavía no hay recorrido ejecutado. Ejecuta una prueba para ver los pasos reales.
      </p>
    );
  }
  return (
    <div data-testid="wf-test-trace">
      <WorkflowRunInspector run={run} plannedEffects={plannedEffects} onSelectNode={onSelectNode} />
    </div>
  );
}
