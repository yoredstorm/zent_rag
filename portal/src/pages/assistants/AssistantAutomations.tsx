import { Plus } from "@phosphor-icons/react";
import { Link } from "react-router-dom";
import { COPY, workflowStatusLabel, type AutomationsPayload } from "./assistantCopy";

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
    <section className="space-y-3" data-testid="assistant-automations">
      <div className="panel space-y-2 p-4">
        <h2 className="text-sm font-semibold text-text">{COPY.automationsTitle}</h2>
        <textarea
          className="min-h-20 w-full resize-y rounded-md border border-border bg-soft px-3 py-2 text-xs"
          placeholder="Cuando un producto se quede sin stock, analiza su nivel de ventas y avisa al gerente."
          value={prompt}
          data-testid="assistant-automation-prompt"
          onChange={(e) => onPromptChange(e.target.value)}
        />
        <p className="text-[10px] text-faint">
          {COPY.automationsHint.replace("este asistente", agentName)}
        </p>
        <button
          type="button"
          className="btn btn-primary min-h-9 gap-1.5 text-xs"
          disabled={prompt.trim().length < 8}
          data-testid="assistant-add-automation"
          onClick={onAdd}
        >
          <Plus size={13} aria-hidden /> Agregar automatización
        </button>
      </div>
      {(automations?.automations.length ?? 0) === 0 ? (
        <p className="panel p-4 text-xs text-muted">{COPY.automationsEmpty}</p>
      ) : (
        <ul className="space-y-2">
          {automations?.automations.map((automation) => (
            <li key={automation.workflow_id} className="panel flex flex-wrap items-center gap-2 p-3 text-[11px]">
              <Link to={`/workflows/${automation.workflow_id}`} className="font-medium text-text hover:text-accent">
                {automation.name}
              </Link>
              <span className={`badge ${automation.status === "active" ? "badge-ok" : "badge-muted"}`}>
                {workflowStatusLabel(automation.status)}
              </span>
              <span className="text-muted">Cuando {automation.when.toLowerCase()}</span>
              <span className="ml-auto text-faint">
                {automation.runs_7d} ejecuciones · {automation.success_rate ?? "—"}% éxito
              </span>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
