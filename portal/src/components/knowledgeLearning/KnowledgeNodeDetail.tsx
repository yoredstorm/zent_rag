// =============================================================================
// KnowledgeNodeDetail — detalle real del nodo (sección 21)
// =============================================================================
import { Database, Graph, Question, Table } from "@phosphor-icons/react";
import { timeAgo } from "../../lib/format";
import { NODE_TYPE_LABELS, type GraphEdge, type GraphNode } from "../../lib/knowledgeGraph";
import { KnowledgeConfidenceBadge } from "./KnowledgeConfidenceBadge";

export function KnowledgeNodeDetail({
  node,
  edges,
  labelOf,
  openQuestions,
  loadingQuestions = false,
}: {
  node: GraphNode | null;
  edges: GraphEdge[];
  labelOf: (nodeId: string) => string;
  openQuestions: string[];
  loadingQuestions?: boolean;
}) {
  if (!node) {
    return (
      <aside className="panel" data-testid="node-detail">
        <p className="text-[13px] text-faint">
          Selecciona un nodo para ver su confianza, evidencia y estado de validación.
        </p>
      </aside>
    );
  }
  const metadata = node.metadata || {};
  const relationships = edges
    .filter((edge) => edge.type === "relationship" && (edge.from === node.id || edge.to === node.id))
    .map((edge) => {
      const other = edge.from === node.id ? edge.to : edge.from;
      const verb = edge.from === node.id ? edge.label : `es relacionado por ${edge.label}`;
      return { id: edge.id, other: labelOf(other), verb, confidence: edge.confidence, cardinality: edge.cardinality };
    });
  const fieldsTotal = Number(metadata.fields_total ?? 0);
  const fieldsUnderstood = Number(metadata.fields_understood ?? 0);
  const columnsTotal = Number(metadata.columns_total ?? 0);
  const synonyms = Array.isArray(metadata.synonyms) ? metadata.synonyms.map(String) : [];

  return (
    <aside className="panel" data-testid="node-detail">
      <div className="flex items-start justify-between gap-2">
        <div className="min-w-0">
          <h3 className="truncate text-sm font-semibold text-text">{node.label}</h3>
          <p className="text-[11px] uppercase tracking-wide text-faint">
            {NODE_TYPE_LABELS[node.type]}
          </p>
        </div>
        <KnowledgeConfidenceBadge confidence={node.confidence} compact />
      </div>

      <div className="mt-2 flex flex-wrap gap-1.5">
        <span className="badge badge-muted" title={node.provenance}>
          {node.provenance}
        </span>
        <span className="badge badge-muted" title={node.validation_state}>
          {node.status}
        </span>
        {node.validation_state === "validated" ? (
          <span className="badge badge-ok">validado</span>
        ) : (
          <span className="badge badge-pending">sin validar</span>
        )}
      </div>

      {node.description && (
        <p className="mt-3 text-[13px] leading-relaxed text-muted">{node.description}</p>
      )}

      <dl className="mt-3 space-y-1.5 text-[12px]">
        {node.source_name && (
          <div className="flex items-center gap-2 text-muted">
            <dt className="flex min-w-16 items-center gap-1 text-faint">
              <Database size={12} aria-hidden /> Fuente
            </dt>
            <dd className="min-w-0 truncate">
              {node.source_name}
              {node.source_id ? ` · ${node.source_id.slice(0, 8)}` : ""}
            </dd>
          </div>
        )}
        {metadata.table ? (
          <div className="flex items-center gap-2 text-muted">
            <dt className="flex min-w-16 items-center gap-1 text-faint">
              <Table size={12} aria-hidden /> Tabla
            </dt>
            <dd className="mono min-w-0 truncate">{String(metadata.table)}</dd>
          </div>
        ) : null}
        {node.type === "entity" && columnsTotal > 0 && (
          <div className="flex items-center gap-2 text-muted">
            <dt className="flex min-w-16 items-center gap-1 text-faint">Campos</dt>
            <dd>
              {fieldsUnderstood}/{fieldsTotal || columnsTotal} entendidos
            </dd>
          </div>
        )}
        {synonyms.length > 0 && (
          <div className="flex items-start gap-2 text-muted">
            <dt className="min-w-16 shrink-0 text-faint">Sinónimos</dt>
            <dd>{synonyms.slice(0, 6).join(", ") || "—"}</dd>
          </div>
        )}
      </dl>

      {relationships.length > 0 && (
        <div className="mt-3">
          <p className="flex items-center gap-1 text-[11px] font-medium uppercase tracking-wide text-faint">
            <Graph size={12} aria-hidden /> Relaciones
          </p>
          <ul className="mt-1 space-y-1 text-[12px] text-muted">
            {relationships.map((relation) => (
              <li key={relation.id} className="flex items-center justify-between gap-2">
                <span className="min-w-0 truncate">
                  {relation.other} <span className="text-faint">· {relation.verb}</span>
                </span>
                {relation.cardinality && (
                  <span className="mono shrink-0 text-faint">{relation.cardinality}</span>
                )}
              </li>
            ))}
          </ul>
        </div>
      )}

      {node.type === "entity" && (
        <div className="mt-3">
          <p className="flex items-center gap-1 text-[11px] font-medium uppercase tracking-wide text-faint">
            <Question size={12} aria-hidden /> Preguntas abiertas
          </p>
          {loadingQuestions ? (
            <p className="mt-1 text-[12px] text-faint">Cargando…</p>
          ) : openQuestions.length === 0 ? (
            <p className="mt-1 text-[12px] text-ok">Sin preguntas pendientes.</p>
          ) : (
            <ul className="mt-1 max-h-28 list-disc space-y-1 overflow-y-auto pl-4 text-[12px] text-muted">
              {openQuestions.map((question) => (
                <li key={question}>{question}</li>
              ))}
            </ul>
          )}
        </div>
      )}

      {node.last_learned_at && (
        <p className="mt-3 text-[11px] text-faint">
          Último aprendizaje: {timeAgo(node.last_learned_at)}
        </p>
      )}
    </aside>
  );
}