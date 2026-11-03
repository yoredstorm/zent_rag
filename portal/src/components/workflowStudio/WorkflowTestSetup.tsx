import type { GraphIssue, WorkflowGraph } from "../../lib/workflowGraph";
import type { NormalizedPayload } from "./types";
import { WorkflowTestComposer } from "./WorkflowTestComposer";
import { WorkflowTestModePicker } from "./WorkflowTestModePicker";
import { WorkflowTestReadiness } from "./WorkflowTestReadiness";
import { flowPreview } from "./workflowTestPresentation";
import type { RealLane, TestLevel, TestReportOut } from "./workflowTestTypes";

export function WorkflowTestSetup({
  level,
  realLane,
  onSelectMode,
  onSelectRealLane,
  raw,
  onChange,
  normalized,
  disabled,
  busy,
  error,
  lastSampleNote,
  canRestore,
  onSubmit,
  onGenerate,
  onUseLast,
  onRestore,
  onApplyExample,
  issues,
  graph,
  effectLabels,
  report,
  onSelectNode,
  status,
}: {
  level: TestLevel;
  realLane: RealLane | null;
  onSelectMode: (mode: "preview" | "simulation" | "real") => void;
  onSelectRealLane: (lane: RealLane) => void;
  raw: string;
  onChange: (value: string) => void;
  normalized: NormalizedPayload;
  disabled?: boolean;
  busy?: boolean;
  error?: string;
  lastSampleNote?: string;
  canRestore?: boolean;
  onSubmit: () => void;
  onGenerate: () => void;
  onUseLast: () => void;
  onRestore: () => void;
  onApplyExample: (message: string) => void;
  issues: GraphIssue[];
  graph?: WorkflowGraph | null;
  effectLabels: string[];
  report: TestReportOut | null;
  onSelectNode: (id: string) => void;
  status: string;
}) {
  return (
    <div className="min-h-0 flex-1 overflow-y-auto">
      <div className="space-y-4 p-3" data-testid="wf-test-setup">
        <WorkflowTestModePicker
          level={level}
          realLane={realLane}
          disabled={disabled || busy}
          onSelectMode={onSelectMode}
          onSelectRealLane={onSelectRealLane}
        />

        <WorkflowTestComposer
          raw={raw}
          onChange={onChange}
          level={level}
          normalized={normalized}
          disabled={disabled}
          busy={busy}
          error={error}
          lastSampleNote={lastSampleNote}
          canRestore={canRestore}
          onSubmit={onSubmit}
          onGenerate={onGenerate}
          onUseLast={onUseLast}
          onRestore={onRestore}
          onApplyExample={onApplyExample}
        />

        <WorkflowTestReadiness
          issues={issues}
          graph={graph}
          level={level}
          report={report}
          effectLabels={effectLabels}
          onSelectNode={onSelectNode}
        />

        <details className="rounded-md border border-border bg-raised/40 px-3 py-2">
          <summary className="cursor-pointer text-[12px] font-medium text-muted select-none">
            Qué hará esta prueba
          </summary>
          <p className="mt-2 text-[11.5px] leading-relaxed text-muted">{flowPreview(graph)}</p>
          {effectLabels.length > 0 ? (
            <p className="mt-1 text-[11.5px] leading-relaxed text-warn">
              {effectLabels.length} nodo(s) con efectos externos: {effectLabels.join(", ")}.
            </p>
          ) : (
            <p className="mt-1 text-[11.5px] leading-relaxed text-faint">
              No se detectaron nodos de escritura en el grafo actual.
            </p>
          )}
        </details>

        {status !== "active" && (
          <p className="text-[11px] leading-relaxed text-faint">
            El workflow está en <span className="font-medium text-muted">{status}</span>. Puedes probar y
            ejecutar, pero el hook público y los schedules no estarán activos hasta publicarlo.
          </p>
        )}
      </div>
    </div>
  );
}
