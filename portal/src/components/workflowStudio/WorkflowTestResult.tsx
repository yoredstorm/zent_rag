import { CheckCircle, Clock, WarningCircle } from "@phosphor-icons/react";
import { Badge, Button, EmptyState, ErrorInline, Spinner, Tabs, TabsContent, TabsList, TabsTrigger } from "../ui";
import { humanizeWorkflowError } from "../../lib/workflowErrors";
import type { WorkflowGraph } from "../../lib/workflowGraph";
import type { RunDetail } from "../WorkflowRunInspector";
import { answerFromSteps, type WorkflowRun } from "./types";
import {
  effectBoundary,
  flowPreview,
  formatElapsed,
  normalizeLevel,
  providerSummary,
  resultHeadline,
  statusMessage,
  testRunSummary,
} from "./workflowTestPresentation";
import type { ResultPane, TestReportOut, TestRunKind } from "./workflowTestTypes";
import { WorkflowTestHistory } from "./WorkflowTestHistory";
import { WorkflowTestTechnical } from "./WorkflowTestTechnical";
import { WorkflowTestTrace } from "./WorkflowTestTrace";
import { WorkflowTestVerification } from "./WorkflowTestVerification";

function Notice({ text, testId = "wf-chat-system" }: { text: string; testId?: string }) {
  if (!text) return null;
  return (
    <p
      className="rounded-md border border-border bg-raised/50 px-3 py-2 text-[12px] leading-relaxed text-muted"
      data-testid={testId}
      role="status"
    >
      {text}
    </p>
  );
}

export function WorkflowTestResult({
  report,
  run,
  runKind,
  operation,
  error,
  providerVerified,
  graph,
  effectLabels,
  selectedPane,
  historicalRun,
  history,
  historyOpen,
  activeRunId,
  elapsedMs,
  onSelectPane,
  onSelectNode,
  onModify,
  onRepeat,
  onRetry,
  onToggleHistory,
  onOpenHistoricalRun,
}: {
  report: TestReportOut | null;
  run: RunDetail | null;
  runKind: TestRunKind | null;
  operation: string;
  error: string;
  providerVerified: boolean;
  graph?: WorkflowGraph | null;
  effectLabels?: string[];
  selectedPane: ResultPane;
  historicalRun?: boolean;
  history: WorkflowRun[];
  historyOpen: boolean;
  activeRunId?: string;
  elapsedMs?: number;
  onSelectPane: (pane: ResultPane) => void;
  onSelectNode: (id: string) => void;
  onModify: () => void;
  onRepeat: () => void;
  onRetry: () => void;
  onToggleHistory: (open: boolean) => void;
  onOpenHistoricalRun: (runId: string) => void;
}) {
  const headline = resultHeadline(report, run, runKind);
  const provider = providerSummary(report);
  const loading = operation === "saving" || operation === "preparing" || operation === "executing" || operation === "loading_result";
  const answer = answerFromSteps(run?.steps);
  const waiting = run?.status === "waiting" || run?.status === "pending_approval";
  const echo = answer?.echo === true;
  const hasResult = Boolean(report || run);

  return (
    <div className="flex min-h-0 flex-1 flex-col" data-testid="wf-test-result">
      <div className="flex items-start gap-2 border-b border-border px-3 py-2.5" aria-live="polite" data-testid="wf-result-headline">
        {headline.tone === "ok" ? (
          <CheckCircle size={16} weight="fill" className="mt-0.5 shrink-0 text-ok" aria-hidden />
        ) : headline.tone === "warn" || headline.tone === "danger" ? (
          <WarningCircle size={16} weight="fill" className={`mt-0.5 shrink-0 ${headline.tone === "danger" ? "text-danger" : "text-warn"}`} aria-hidden />
        ) : (
          <Clock size={16} className="mt-0.5 shrink-0 text-muted" aria-hidden />
        )}
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-1.5">
            <p className="text-[13px] font-medium text-text">{headline.label}</p>
            {report && <Badge tone={headline.tone}>{report.result}</Badge>}
            {run?.status && runKind === "execution_run" && <Badge tone={headline.tone}>{run.status}</Badge>}
          </div>
          <p className="mt-0.5 text-[11.5px] leading-relaxed text-muted">{headline.detail}</p>
          {report && (
            <p className="mt-0.5 text-[11px] text-faint">
              {testRunSummary(report)} · {provider.label}
            </p>
          )}
          {runKind === "execution_run" && run && (
            <p className="mt-0.5 text-[11px] text-faint">Corrida real · {run.id}</p>
          )}
        </div>
      </div>

      {historicalRun && (
        <div className="border-b border-border px-3 py-2">
          <Notice
            testId="wf-historical-result"
            text="Resultado histórico. No es el estado actual del grafo; el lienzo muestra la corrida abierta."
          />
        </div>
      )}

      {loading && (
        <div className="flex items-center gap-2 border-b border-border px-3 py-2 text-[12px] text-muted" role="status">
          <Spinner size={14} />
          <span>{operation === "saving" ? "Guardando el grafo antes de probar…" : "Preparando la prueba…"}</span>
          {elapsedMs != null && <span className="ml-auto tabular-nums text-faint">{formatElapsed(elapsedMs)}</span>}
        </div>
      )}

      {error && (
        <div className="border-b border-border px-3 py-2">
          <ErrorInline message={error} className="mb-0" />
          <Button variant="secondary" size="sm" className="mt-2" onClick={onRetry} data-testid="wf-result-retry">
            Volver a intentar
          </Button>
        </div>
      )}

      {!hasResult && !loading && !error ? (
        <div className="flex min-h-0 flex-1 items-center justify-center p-4">
          <EmptyState
            compact
            title="Sin resultado todavía"
            body="Prepara una prueba y ejecútala. El resultado aparecerá aquí sin mover el lienzo."
          />
        </div>
      ) : (
        <Tabs
          value={selectedPane}
          onValueChange={(value) => onSelectPane(value as ResultPane)}
          variant="pill"
          className="flex min-h-0 flex-1 flex-col"
        >
          <TabsList className="mx-3 mt-2">
            <TabsTrigger value="answer" data-testid="wf-result-tab-answer">
              Respuesta
            </TabsTrigger>
            <TabsTrigger value="path" data-testid="wf-result-tab-path">
              Recorrido
            </TabsTrigger>
            <TabsTrigger value="verification" data-testid="wf-result-tab-verification">
              Verificación
            </TabsTrigger>
          </TabsList>

          <TabsContent value="answer" className="mt-2 min-h-0 flex-1 overflow-y-auto px-3 pb-2">
            <div className="space-y-2.5">
              {waiting && (
                <Notice
                  text={
                    run?.status === "pending_approval"
                      ? "Esperando aprobación humana. La corrida no terminó; no hay respuesta final todavía."
                      : "Esperando mensaje o señal. La corrida quedó en espera; no hay respuesta final todavía."
                  }
                />
              )}

              {report && <Notice text={statusMessage(report, runKind)} />}

              {!waiting && answer?.error && (
                <ErrorInline message={humanizeWorkflowError(answer.error)} className="mb-0" />
              )}

              {!waiting && answer && !answer.error && (
                <article className="rounded-md border border-border bg-raised/40 px-3 py-2.5">
                  <div className="mb-1 flex flex-wrap items-center gap-1.5">
                    <Badge tone="ok">Respuesta</Badge>
                    {echo && <Badge tone="warn">Eco de ejemplo</Badge>}
                  </div>
                  <p className="whitespace-pre-wrap text-[13px] leading-relaxed text-text" data-testid="wf-chat-answer">
                    {answer.text}
                  </p>
                  {echo && (
                    <p className="mt-1.5 text-[11.5px] leading-relaxed text-warn" data-testid="wf-chat-echo">
                      Esto es una respuesta de ejemplo, no de un agente configurado. Asigna un agente al
                      nodo que responde.
                    </p>
                  )}
                  {answer.node_id && (
                    <Button
                      variant="ghost"
                      size="sm"
                      className="mt-1.5 px-0"
                      onClick={() => onSelectNode(answer.node_id as string)}
                      data-testid="wf-select-answer-node"
                    >
                      Seleccionar nodo en el lienzo
                    </Button>
                  )}
                </article>
              )}

              {!waiting && !answer && !error && (
                <EmptyState
                  compact
                  title="Sin respuesta legible"
                  body={
                    report
                      ? report.why || "El reporte no contiene una respuesta de agente."
                      : "La corrida terminó sin texto de respuesta."
                  }
                />
              )}

              <div className="rounded-md border border-border bg-raised/40 px-3 py-2.5">
                <p className="text-[12px] font-medium text-text">Qué hará esta prueba</p>
                <p className="mt-1 text-[11.5px] leading-relaxed text-muted">{flowPreview(graph)}</p>
                <p className="mt-1 text-[11.5px] leading-relaxed text-faint">
                  {effectBoundary(normalizeLevel(report?.effective_level ?? "simulation"))}
                </p>
              </div>

              <WorkflowTestHistory
                runs={history}
                open={historyOpen}
                activeRunId={activeRunId}
                onToggle={onToggleHistory}
                onOpen={onOpenHistoricalRun}
              />
            </div>
          </TabsContent>

          <TabsContent value="path" className="mt-2 min-h-0 flex-1 overflow-y-auto px-3 pb-2">
            <WorkflowTestTrace run={run} plannedEffects={run?.planned_effects} onSelectNode={onSelectNode} />
          </TabsContent>

          <TabsContent value="verification" className="mt-2 min-h-0 flex-1 overflow-y-auto px-3 pb-2">
            <div className="space-y-2.5">
              <WorkflowTestVerification
                report={report}
                run={run}
                plannedEffects={run?.planned_effects}
                providerVerified={providerVerified}
                effectLabels={effectLabels}
              />
              <WorkflowTestTechnical report={report} run={run} />
            </div>
          </TabsContent>
        </Tabs>
      )}

      <div className="flex flex-wrap items-center justify-between gap-2 border-t border-border px-3 py-2.5">
        <Button variant="secondary" size="sm" onClick={onModify} data-testid="wf-modify-test">
          Modificar prueba
        </Button>
        <Button
          variant="primary"
          size="sm"
          onClick={onRepeat}
          disabled={loading}
          data-testid="wf-repeat-test"
        >
          {runKind === "execution_run" ? "Repetir ejecución" : "Repetir prueba"}
        </Button>
      </div>
    </div>
  );
}
