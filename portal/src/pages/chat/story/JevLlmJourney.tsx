import type { ExecutionNarrative } from "../executionNarrative";

const NODE_LABELS: Record<string, string> = {
  QUERY_UNDERSTOOD: "Zent entendió la consulta",
  REQUIREMENTS_IDENTIFIED: "Definió qué debía comprobar",
  KNOWLEDGE_SEARCHED: "Consultó el conocimiento",
  EVIDENCE_FOUND: "Encontró evidencia",
  JEV_CHECKED: "JEV revisó el camino",
  JEV_CHANGED_PATH: "JEV cambió el camino",
  SEARCH_RETRIED: "Amplió la búsqueda",
  EVIDENCE_COMPLETE: "El motor confirmó cobertura completa",
  EVIDENCE_INCOMPLETE: "El motor detectó requisitos pendientes",
  LLM_ANALYZED: "El modelo analizó la evidencia",
  ANSWER_DRAFTED: "El modelo redactó la respuesta",
  ANSWER_REVISED: "La respuesta fue corregida",
  ANSWER_VERIFIED: "Zent verificó la respuesta",
  ANSWER_DELIVERED: "Entregó la respuesta",
};

export function JevLlmJourney({ narrative }: { narrative: ExecutionNarrative }) {
  if (!narrative.journey.length) return null;
  return (
    <details className="rounded-md border border-border-soft px-3 py-2">
      <summary className="cursor-pointer text-[11.5px] font-medium text-accent">
        Cómo colaboraron JEV y el modelo
      </summary>
      <ol className="mt-3 flex flex-col gap-0">
        {narrative.journey.map((node, index) => (
          <li key={node.id} className="relative flex gap-2 pb-3 last:pb-0">
            {index < narrative.journey.length - 1 ? (
              <span className="absolute left-[5px] top-3 h-full w-px bg-border" aria-hidden />
            ) : null}
            <span className="relative mt-1 h-2.5 w-2.5 shrink-0 rounded-full border border-accent bg-surface" />
            <span className="text-[11.5px] text-muted">
              {NODE_LABELS[node.kind] ?? node.kind.replace(/_/g, " ")}
            </span>
          </li>
        ))}
      </ol>
    </details>
  );
}

export default JevLlmJourney;
