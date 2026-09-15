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
      className="rounded-md border border-border bg-soft/60 px-2 py-1.5"
      data-testid="wf-node-help"
    >
      <summary className="cursor-pointer text-[10px] font-semibold text-muted">
        ¿Qué hace este paso?
      </summary>
      <div className="mt-1.5 space-y-1 text-[10px] text-muted">
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
          <p className="font-mono text-[9px] text-faint" data-testid="wf-node-help-example">
            {JSON.stringify(meta.example).slice(0, 220)}
          </p>
        )}
        {(meta.recommendedNext?.length ?? 0) > 0 && (
          <div className="pt-0.5" data-testid="wf-node-help-next">
            <span className="text-faint">Siguientes pasos: </span>
            <span className="inline-flex flex-wrap gap-1">
              {meta.recommendedNext!.map((next) => (
                <button
                  key={next.node_type}
                  type="button"
                  className="rounded border border-border bg-bg px-1.5 py-0.5 text-[9px] text-accent hover:border-accent/50"
                  data-testid={`wf-next-${next.node_type}`}
                  onClick={() => onAddSuggested?.(next.node_type)}
                >
                  {next.label}
                </button>
              ))}
            </span>
          </div>
        )}
      </div>
    </details>
  );
}
