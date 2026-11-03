import { CheckCircle, Question, WarningCircle } from "@phosphor-icons/react";
import type { ReactNode } from "react";
import { Badge, Button } from "../ui";
import type { GraphIssue, WorkflowGraph } from "../../lib/workflowGraph";
import { LEVEL_DESCRIPTION, LEVEL_LABEL, normalizeLevel } from "./workflowTestPresentation";
import type { TestLevel, TestReportOut } from "./workflowTestTypes";

type RowTone = "ok" | "warn" | "danger" | "neutral" | "info";

function Row({
  label,
  tone,
  status,
  detail,
  action,
}: {
  label: string;
  tone: RowTone;
  status: string;
  detail: string;
  action?: ReactNode;
}) {
  const Icon = tone === "ok" ? CheckCircle : tone === "warn" || tone === "danger" ? WarningCircle : Question;
  return (
    <div className="flex items-start gap-2 border-b border-border-soft py-2 last:border-0">
      <Icon
        size={14}
        weight={tone === "ok" ? "fill" : "regular"}
        className={`mt-0.5 shrink-0 ${
          tone === "ok" ? "text-ok" : tone === "danger" ? "text-danger" : tone === "warn" ? "text-warn" : "text-faint"
        }`}
        aria-hidden
      />
      <div className="min-w-0 flex-1">
        <div className="flex flex-wrap items-center gap-1.5">
          <span className="text-[12px] font-medium text-text">{label}</span>
          <Badge tone={tone}>{status}</Badge>
        </div>
        <p className="mt-0.5 text-[11.5px] leading-relaxed text-muted">{detail}</p>
        {action}
      </div>
    </div>
  );
}

export function WorkflowTestReadiness({
  issues,
  graph,
  level,
  report,
  effectLabels,
  onSelectNode,
}: {
  issues: GraphIssue[];
  graph?: WorkflowGraph | null;
  level: TestLevel;
  report: TestReportOut | null;
  effectLabels: string[];
  onSelectNode: (id: string) => void;
}) {
  const effective = report ? normalizeLevel(report.effective_level) : null;
  const requested = report ? normalizeLevel(report.requested_level) : level;
  const adjusted = Boolean(report && requested !== effective);
  const graphTone: RowTone = issues.length > 0 ? "warn" : "ok";
  const modeTone: RowTone = adjusted ? "warn" : level === "preview" ? "info" : "ok";
  const selectedReadiness =
    level === "provider"
      ? report?.readiness?.provider_ready
      : level === "sandbox"
        ? report?.readiness?.sandbox_ready
        : undefined;
  const dependencyReady = selectedReadiness === true;
  const dependencyUnavailable = selectedReadiness === false;
  const dependencyTone: RowTone = dependencyUnavailable ? "warn" : dependencyReady ? "ok" : "neutral";

  return (
    <details className="rounded-md border border-border bg-raised/40 px-3 py-2" data-testid="wf-readiness">
      <summary className="cursor-pointer text-[12px] font-medium text-muted select-none">
        Preparación para probar
      </summary>
      <div className="mt-1">
        <Row
          label="Grafo"
          tone={graphTone}
          status={issues.length === 0 ? "Listo" : "Revisar"}
          detail={
            issues.length === 0
              ? "Sin avisos que impidan interpretar la prueba."
              : `${issues[0].label}: ${issues[0].message}`
          }
          action={
            issues.length > 0 ? (
              <div className="mt-1 space-y-1" data-testid="wf-issues">
                {issues.slice(0, 3).map((issue) => (
                  <Button
                    key={`${issue.node_id}-${issue.message}`}
                    variant="ghost"
                    size="sm"
                    className="h-auto min-h-0 justify-start px-0 py-0.5 text-left text-[11px] text-muted hover:text-accent"
                    onClick={() => onSelectNode(issue.node_id)}
                    data-testid="wf-issue-jump"
                  >
                    Ir al nodo: {issue.label}
                  </Button>
                ))}
              </div>
            ) : undefined
          }
        />
        <Row
          label="Modo"
          tone={modeTone}
          status={adjusted ? `Ajustado a ${LEVEL_LABEL[effective ?? "simulation"]}` : LEVEL_LABEL[level]}
          detail={LEVEL_DESCRIPTION[level]}
        />
        <Row
          label="Dependencias externas"
          tone={dependencyTone}
          status={dependencyUnavailable ? "No disponible" : dependencyReady ? "Disponible en el último reporte" : "No verificado"}
          detail={
            effectLabels.length === 0
              ? "El grafo no declara nodos de escritura."
              : `${effectLabels.length} nodo(s) con efectos: ${effectLabels.join(", ")}.`
          }
        />
      </div>
      <details className="mt-2 border-t border-border-soft pt-2">
        <summary className="cursor-pointer text-[11px] font-medium text-muted select-none">
          Qué ejecuta cada modo
        </summary>
        <ul className="mt-1.5 space-y-1.5 text-[11.5px] leading-relaxed text-muted">
          {(["preview", "simulation", "sandbox", "provider"] as TestLevel[]).map((item) => (
            <li key={item}>
              <span className="font-medium text-text">{LEVEL_LABEL[item]}:</span> {LEVEL_DESCRIPTION[item]}
            </li>
          ))}
        </ul>
        <p className="mt-1.5 text-[11px] text-faint">
          {graph ? "La explicación se basa en los nodos actuales del grafo." : "Sin grafo cargado."}
        </p>
      </details>
    </details>
  );
}
