import { Plus } from "@phosphor-icons/react";
import { Link } from "react-router-dom";
import { Badge, Button, EmptyState, Field, Panel, PanelHeader, Textarea } from "../../components/ui";
import { COPY, workflowStatusLabel, type AutomationsPayload } from "./assistantCopy";

/** Estado real del flujo para el activity rail. */
function railState(status: string): "ready" | "queued" | "failed" {
  if (status === "active") return "ready";
  if (status === "failed" || status === "error") return "failed";
  return "queued";
}

export function AssistantAutomations({
  agentName,
  automations,
  prompt,
  onPromptChange,
  onAdd,
}: {
  agentName: string;
  automations: AutomationsPayload | null;
  prompt: string;
  onPromptChange: (value: string) => void;
  onAdd: () => void;
}) {
  return (
    <section className="grid gap-4" data-testid="assistant-automations">
      <Panel>
        <PanelHeader
          title={COPY.automationsTitle}
          description="Describe qué debe vigilar. El copiloto propone el flujo."
        />
        <div className="grid gap-3 p-4">
          <Field
            id="assistant-automation-prompt"
            label="Qué debe vigilar"
            hint={COPY.automationsHint.replace("este asistente", agentName)}
          >
            <Textarea
              id="assistant-automation-prompt"
              className="min-h-20 text-[13px]"
              placeholder="Cuando un producto se quede sin stock, analiza su nivel de ventas y avisa al gerente."
              value={prompt}
              data-testid="assistant-automation-prompt"
              onChange={(e) => onPromptChange(e.target.value)}
            />
          </Field>
          <div className="flex justify-end">
            <Button
              variant="primary"
              leadingIcon={Plus}
              disabled={prompt.trim().length < 8}
              data-testid="assistant-add-automation"
              onClick={onAdd}
            >
              Agregar automatización
            </Button>
          </div>
        </div>
      </Panel>

      {(automations?.automations.length ?? 0) === 0 ? (
        <Panel>
          <EmptyState icon={Plus} title="Sin automatizaciones" body={COPY.automationsEmpty} compact />
        </Panel>
      ) : (
        <ul className="grid gap-3">
          {automations?.automations.map((automation) => (
            <li key={automation.workflow_id}>
              <article className="panel" data-state={railState(automation.status)}>
                <div className="state-rail flex flex-wrap items-center gap-x-3 gap-y-2 p-4 pl-5 text-[13px]">
                  <Link
                    to={`/workflows/${automation.workflow_id}`}
                    className="font-medium text-text hover:text-accent"
                  >
                    {automation.name}
                  </Link>
                  <Badge tone={automation.status === "active" ? "ok" : "neutral"}>
                    {workflowStatusLabel(automation.status)}
                  </Badge>
                  <span className="min-w-0 flex-1 text-muted">
                    Cuando {automation.when.toLowerCase()}
                  </span>
                  <span className="text-xs text-faint tabular-nums">
                    {automation.runs_7d} ejecuciones · {automation.success_rate ?? "—"}% éxito
                    {automation.failed_runs > 0 ? ` · ${automation.failed_runs} con fallos` : ""}
                  </span>
                </div>
              </article>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
