import { useEffect, useMemo, useRef, useState } from "react";
import { clampTestResultWidth, TEST_RESULT_WIDTH } from "../../lib/studioLayout";
import { isConversationalGraph, type GraphIssue, type WorkflowGraph } from "../../lib/workflowGraph";
import { Badge, ConfirmDialog, Tabs, TabsContent, TabsList, TabsTrigger } from "../ui";
import type { RunDetail } from "../WorkflowRunInspector";
import { WorkflowTestFooter } from "./WorkflowTestFooter";
import { WorkflowTestHeader } from "./WorkflowTestHeader";
import { WorkflowTestResult } from "./WorkflowTestResult";
import { WorkflowTestSetup } from "./WorkflowTestSetup";
import { ResizeHandle } from "./ResizeHandle";
import { normalizeTestPayload } from "./types";
import { generateSampleForGraph, normalizeLevel } from "./workflowTestPresentation";
import type { RealLane, TestLevel } from "./workflowTestTypes";
import { useWorkflowTestRunner } from "./useWorkflowTestRunner";

type Props = {
  workflowId: string;
  status: string;
  /** Nodos de escritura del grafo: se confirman antes de ejecutar de verdad. */
  effectLabels: string[];
  /** Avisos del grafo (nodo `llm` sin agente, etc.). */
  issues: GraphIssue[];
  dirty: boolean;
  /** Alimenta el overlay del lienzo con el run recién hecho. */
  onRun: (run: RunDetail | null) => void;
  onSelectNode: (id: string) => void;
  onRan?: () => void;
  /**
   * Persiste el grafo antes de correr. El motor ejecuta la versión guardada:
   * sin esto el usuario prueba lo que hay en el servidor, no lo que ve.
   */
  onSaveBeforeRun?: () => Promise<boolean>;
  /** Grafo actual: genera ejemplos de prueba coherentes con el flujo. */
  graph?: WorkflowGraph | null;
  /** El estudio lo monta dentro del Drawer inferior: oculta el encabezado propio. */
  embedded?: boolean;
  /** Huella del grafo actual para comparar el historial. */
  graphHash?: string | null;
  /** Desktop: entrada a la izquierda y resultado a la derecha, sin tabs. */
  split?: boolean;
  /** Ancho del resultado en el modo dividido. Si falta, el panel lo recuerda en memoria. */
  resultWidth?: number;
  onResultWidthChange?: (width: number) => void;
};

export function WorkflowTestPanel({
  workflowId,
  status,
  effectLabels,
  issues,
  dirty,
  onRun,
  onSelectNode,
  onRan,
  onSaveBeforeRun,
  graph,
  embedded = false,
  graphHash,
  split = false,
  resultWidth: resultWidthProp,
  onResultWidthChange,
}: Props) {
  const [raw, setRaw] = useState("");
  const [realLane, setRealLane] = useState<RealLane | null>(null);
  const [formError, setFormError] = useState("");
  const [lastSampleNote, setLastSampleNote] = useState("");
  const [restoreRaw, setRestoreRaw] = useState<string | null>(null);
  const [confirmOpen, setConfirmOpen] = useState(false);
  const [localResultWidth, setLocalResultWidth] = useState(TEST_RESULT_WIDTH.initial);
  const splitRef = useRef<HTMLDivElement>(null);
  const [splitWidth, setSplitWidth] = useState(0);
  const resultWidth = resultWidthProp ?? localResultWidth;

  const conversational = useMemo(() => isConversationalGraph(graph), [graph]);
  const {
    state,
    dispatch,
    runs,
    busy,
    elapsedMs,
    executeTest,
    confirmRealRun,
    sendMessage,
    refreshInstance,
    loadLastSample,
    showRun,
  } = useWorkflowTestRunner({
    workflowId,
    dirty,
    hasRealLane: Boolean(realLane),
    conversational,
    onRun,
    onRan,
    onSaveBeforeRun,
  });

  const normalized = useMemo(() => normalizeTestPayload(raw), [raw]);
  const hasInput = raw.trim().length > 0;
  const hasResult = Boolean(state.report || state.run);
  const currentMode: "preview" | "simulation" | "real" =
    state.requestedLevel === "preview" || state.requestedLevel === "simulation"
      ? state.requestedLevel
      : "real";

  useEffect(() => {
    const el = splitRef.current;
    if (!el || !split || typeof ResizeObserver === "undefined") return;
    const apply = () => setSplitWidth(el.clientWidth);
    apply();
    const observer = new ResizeObserver(apply);
    observer.observe(el);
    return () => observer.disconnect();
  }, [split]);

  useEffect(() => {
    setRaw("");
    setRealLane(null);
    setFormError("");
    setLastSampleNote("");
    setRestoreRaw(null);
    setConfirmOpen(false);
  }, [workflowId]);

  function runTest(level: TestLevel, allowReal = false) {
    setFormError("");
    void executeTest(level, raw, allowReal).then((message) => {
      if (message) setFormError(message);
    });
  }

  function selectMode(mode: "preview" | "simulation" | "real") {
    setFormError("");
    if (mode === "preview" || mode === "simulation") {
      setRealLane(null);
      dispatch({ type: "select-level", level: mode });
      return;
    }
    setRealLane(null);
    dispatch({ type: "select-level", level: "sandbox" });
  }

  function selectRealLane(lane: RealLane) {
    setRealLane(lane);
    dispatch({ type: "select-level", level: lane });
  }

  function applyExample(message: string) {
    setRestoreRaw(raw);
    setRaw(message);
    setLastSampleNote("Mensaje de ejemplo. No cambia tu agente, tus herramientas ni el workflow.");
    setFormError("");
  }

  function generateSample() {
    setRestoreRaw(raw);
    setRaw(generateSampleForGraph(graph));
    setLastSampleNote("Ejemplo generado a partir de los nodos del grafo. Editable antes de probar.");
    setFormError("");
  }

  async function applyLastSample() {
    if (busy) return;
    setFormError("");
    const result = await loadLastSample();
    if (result.error) setFormError(result.error);
    if (result.payload !== undefined) {
      setRestoreRaw(raw);
      setRaw(result.payload);
    }
    setLastSampleNote(result.note);
  }

  function restoreDraft() {
    setRaw(restoreRaw ?? "");
    setRestoreRaw(null);
    setLastSampleNote("");
    setFormError("");
  }

  function repeat() {
    if (state.runKind === "execution_run") {
      setConfirmOpen(true);
      return;
    }
    runTest(normalizeLevel(state.report?.requested_level ?? state.requestedLevel), true);
  }

  function retry() {
    if (state.runKind === "execution_run") {
      setConfirmOpen(true);
      return;
    }
    runTest(normalizeLevel(state.report?.requested_level ?? state.requestedLevel), true);
  }

  const ctaLabel =
    currentMode === "preview"
      ? "Ver vista previa"
      : currentMode === "simulation"
        ? "Ejecutar simulación"
        : realLane === "sandbox"
          ? "Probar en sandbox"
          : realLane === "provider"
            ? "Solicitar certificación con proveedor"
            : "Elige sandbox o proveedor";
  const ctaDisabled =
    busy ||
    (currentMode === "real" && !realLane) ||
    (currentMode !== "preview" && !hasInput);

  const setupPane = (
    <WorkflowTestSetup
      level={state.requestedLevel}
      realLane={realLane}
      onSelectMode={selectMode}
      onSelectRealLane={selectRealLane}
      raw={raw}
      onChange={(value) => {
        setRaw(value);
        setLastSampleNote("");
        setFormError("");
      }}
      normalized={normalized}
      disabled={busy}
      busy={busy}
      error={formError || state.error}
      lastSampleNote={lastSampleNote}
      canRestore={restoreRaw !== null && restoreRaw !== raw}
      onSubmit={() => runTest(state.requestedLevel)}
      onGenerate={generateSample}
      onUseLast={() => void applyLastSample()}
      onRestore={restoreDraft}
      onApplyExample={applyExample}
      issues={issues}
      graph={graph}
      effectLabels={effectLabels}
      report={state.report}
      onSelectNode={onSelectNode}
      status={status}
    />
  );

  const resultPane = (
    <WorkflowTestResult
      report={state.report}
      run={state.run}
      runKind={state.runKind}
      operation={state.operation}
      error={state.error}
      providerVerified={state.providerVerified}
      graph={graph}
      effectLabels={effectLabels}
      selectedPane={state.selectedPane}
      historicalRun={state.historicalRun}
      history={runs}
      historyOpen={state.historyOpen}
      activeRunId={state.activeRunId}
      elapsedMs={elapsedMs}
      durableStatus={state.durableStatus}
      durableNotice={state.durableNotice}
      currentGraphHash={graphHash}
      onSendMessage={sendMessage}
      onApprovalDecided={() => void refreshInstance()}
      onSelectPane={(pane) => dispatch({ type: "show-result", pane })}
      onSelectNode={onSelectNode}
      onModify={() => dispatch({ type: "show-setup" })}
      onRepeat={repeat}
      onRetry={retry}
      onToggleHistory={(open) => dispatch({ type: "toggle-history", open })}
      onOpenHistoricalRun={(runId) => void showRun(runId)}
      showModify={!split}
    />
  );

  const footer = (
    <WorkflowTestFooter
      ctaLabel={ctaLabel}
      ctaDisabled={ctaDisabled}
      busy={busy}
      hasInput={hasInput}
      effectLabels={effectLabels}
      onTest={() => runTest(state.requestedLevel)}
      onRealRun={() => setConfirmOpen(true)}
    />
  );

  return (
    <section
      className="panel flex min-h-0 w-full flex-1 flex-col overflow-hidden"
      data-testid="wf-test-panel"
      aria-label="Probar el workflow"
    >
      <WorkflowTestHeader
        embedded={embedded}
        status={status}
        dirty={dirty}
        saving={state.operation === "saving"}
      />

      {split ? (
        <div ref={splitRef} className="flex min-h-0 flex-1">
          <div className="flex min-h-0 min-w-0 flex-1 flex-col border-r border-border">
            <div className="flex shrink-0 items-center gap-2 border-b border-border px-3 py-2">
              <p className="text-[13px] font-semibold text-text">Entrada</p>
              <span className="text-[11px] text-faint">Mensaje o payload que activa el flujo</span>
            </div>
            {setupPane}
            {footer}
          </div>
          <div
            className="relative flex min-h-0 shrink-0 flex-col"
            style={{ width: clampTestResultWidth(resultWidth, splitWidth) }}
            data-testid="wf-test-result-pane"
          >
            <ResizeHandle
              axis="x"
              value={clampTestResultWidth(resultWidth, splitWidth)}
              min={TEST_RESULT_WIDTH.min}
              max={clampTestResultWidth(Number.POSITIVE_INFINITY, splitWidth)}
              resetTo={TEST_RESULT_WIDTH.initial}
              onChange={(width) => {
                const next = clampTestResultWidth(width, splitWidth);
                if (onResultWidthChange) onResultWidthChange(next);
                else setLocalResultWidth(next);
              }}
              label="Ancho del resultado"
              testId="wf-test-split-resize"
            />
            <div className="flex shrink-0 items-center gap-2 border-b border-border px-3 py-2">
              <p className="text-[13px] font-semibold text-text">Resultado del flujo</p>
              {state.historicalRun && <Badge tone="neutral">Histórico</Badge>}
            </div>
            {resultPane}
          </div>
        </div>
      ) : (
        <>
          <Tabs
            value={state.view}
            onValueChange={(value) => {
              if (value === "result") dispatch({ type: "show-result" });
              else dispatch({ type: "show-setup" });
            }}
            className="flex min-h-0 flex-1 flex-col"
          >
            <TabsList className="mx-3 mt-2">
              <TabsTrigger value="setup" data-testid="wf-test-tab-setup">
                Probar
              </TabsTrigger>
              <TabsTrigger value="result" data-testid="wf-test-tab-result">
                Resultado{hasResult ? "" : " · vacío"}
              </TabsTrigger>
            </TabsList>

            <TabsContent value="setup" className="mt-0 flex min-h-0 flex-1 flex-col overflow-hidden">
              {setupPane}
            </TabsContent>

            <TabsContent value="result" className="mt-0 flex min-h-0 flex-1 flex-col overflow-hidden">
              {resultPane}
            </TabsContent>
          </Tabs>

          {state.view === "setup" && footer}
        </>
      )}

      <ConfirmDialog
        open={confirmOpen}
        onOpenChange={setConfirmOpen}
        title="Ejecutar workflow con efectos reales"
        body={
          effectLabels.length > 0
            ? `Ejecutar no es una prueba. Va a disparar ${effectLabels.length} nodo(s) con efectos externos: ${effectLabels.join(", ")}. El servidor aplicará permisos y aprobaciones.`
            : "Ejecutar no es una prueba. No se detectaron nodos de escritura en el grafo actual, pero la operación real puede tener efectos. El servidor aplicará permisos y aprobaciones."
        }
        confirmLabel="Ejecutar de verdad"
        cancelLabel="Cancelar"
        tone="danger"
        requireText="EJECUTAR"
        requireTextLabel="Escribe EJECUTAR para confirmar"
        onConfirm={() => {
          setConfirmOpen(false);
          void confirmRealRun(normalized.payload);
        }}
      />
    </section>
  );
}
