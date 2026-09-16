import { CaretDown, Question } from "@phosphor-icons/react";
import type { NodeMeta } from "../../lib/workflowGraph";

type Props = {
  meta: NodeMeta;
  onAddSuggested?: (nodeType: string) => void;
};

/**
 * Ayuda contextual de negocio por nodo (Fase 8, brief §18):
 * qué hace, cuándo usarlo, qué necesita, qué produce y un ejemplo.
 */
export function NodeHelpCard({ meta, onAddSuggested }: Props) {
  const hasHelp = Boolean(
    meta.longDescription ||
      meta.whenToUse?.length ||
      meta.whatItNeeds?.length ||
      meta.whatItProduces?.length ||
      meta.example != null
  );
  if (!hasHelp) return null;
  return (
    <details
      className="group rounded-md border border-border-soft bg-soft/50"
      data-testid="wf-node-help"
    >
      <summary className="flex cursor-pointer list-none items-center gap-1.5 px-2.5 py-2 text-[12px] font-medium text-muted transition-colors duration-150 hover:text-text">
        <Question size={12} aria-hidden />
        ¿Qué hace este paso?
        <CaretDown size={10} className="ml-auto transition-transform duration-150 group-open:rotate-180" aria-hidden />
      </summary>
      <div className="space-y-1.5 border-t border-border-soft px-2.5 py-2 text-[12px] leading-relaxed text-muted">
        {meta.longDescription && (
          <p data-testid="wf-node-help-does">{meta.longDescription}</p>
        )}
        {(meta.whenToUse?.length ?? 0) > 0 && (
          <p data-testid="wf-node-help-when">
            <span className="text-faint">Úsalo cuando: </span>
            {meta.whenToUse!.join(" · ")}
          </p>
        )}
        {(meta.whatItNeeds?.length ?? 0) > 0 && (
          <p data-testid="wf-node-help-needs">
            <span className="text-faint">Necesita: </span>
            {meta.whatItNeeds!.join(", ")}
          </p>
        )}
        {(meta.whatItProduces?.length ?? 0) > 0 && (
          <p data-testid="wf-node-help-produces">
            <span className="text-faint">Produce: </span>
            {meta.whatItProduces!.join(", ")}
          </p>
        )}
        {meta.example != null && (
          <p
            className="rounded-sm bg-control px-2 py-1.5 font-mono text-[11px] break-all text-faint"
            data-testid="wf-node-help-example"
          >
            {JSON.stringify(meta.example).slice(0, 220)}
          </p>
        )}
        {(meta.recommendedNext?.length ?? 0) > 0 && (
          <div className="flex flex-wrap items-center gap-1 pt-0.5" data-testid="wf-node-help-next">
            <span className="text-faint">Siguientes pasos: </span>
            {meta.recommendedNext!.map((next) => (
              <button
                key={next.node_type}
                type="button"
                className="cursor-pointer rounded-sm border border-border bg-surface px-1.5 py-0.5 text-[11px] text-accent transition-colors duration-150 hover:border-accent-line hover:bg-accent-soft"
                data-testid={`wf-next-${next.node_type}`}
                onClick={() => onAddSuggested?.(next.node_type)}
              >
                {next.label}
              </button>
            ))}
          </div>
        )}
      </div>
    </details>
  );
}
