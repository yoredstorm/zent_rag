// =============================================================================
// Explorador — Dominio → Tipo → Objeto → Hecho → Evidencia → Fuente
// =============================================================================
import { useCallback, useEffect, useMemo, useState } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import {
  ArrowRight,
  BookOpen,
  Graph,
  ListBullets,
  MagnifyingGlass,
  X,
} from "@phosphor-icons/react";import {
  Button,
  ButtonLink,
  EmptyState,
  ErrorInline,
  Panel,
  Select,
  Skeleton,
  cn,
} from "../../components/ui";
import { KnowledgeLayout } from "../../components/KnowledgeLayout";
import { KnowledgeConfidenceBadge } from "../../components/knowledgeLearning/KnowledgeConfidenceBadge";
import {
  fetchKnowledgeCorpora,
  fetchKnowledgeDomains,
  fetchKnowledgeGraph,
  fetchKnowledgeObjects,
  fetchKnowledgeSourceInsight,
  fetchKnowledgeSources,
  objectTypeLabel,
  statusTone,
  type KnowledgeDomain,
  type KnowledgeExplorerInsightPayload,
  type KnowledgeGraphPayload,
  type KnowledgeObject,
  type KnowledgeSourceSummary,
} from "../../lib/knowledgeModel";
import { timeAgo } from "../../lib/format";
import { loadSession } from "../../api";

const TYPE_OPTIONS = [
  { value: "", label: "Todos los tipos" },
  { value: "entity", label: "Entidades" },
  { value: "concept", label: "Conceptos" },
  { value: "business_rule", label: "Reglas de negocio" },
  { value: "metric", label: "Métricas" },
  { value: "process", label: "Procesos" },
  { value: "term", label: "Términos" },
  { value: "relationship", label: "Relaciones" },
  { value: "attribute", label: "Atributos" },
  { value: "table", label: "Tablas" },
  { value: "column", label: "Columnas" },
  { value: "source", label: "Fuentes" },
  { value: "document", label: "Documentos" },
  { value: "domain", label: "Dominios" },
];

const STATUS_OPTIONS = [
  { value: "", label: "Cualquier estado" },
  { value: "verified", label: "Verificados" },
  { value: "inferred", label: "Inferidos" },
  { value: "discovered", label: "Descubiertos" },
  { value: "draft", label: "Borrador" },
  { value: "deprecated", label: "Obsoletos" },
];

const ORDER_OPTIONS = [
  { value: "updated_at", label: "Actualizados" },
  { value: "confidence", label: "Confianza" },
  { value: "evidence", label: "Evidencia" },
  { value: "name", label: "Nombre" },
];

const PAGE_SIZE = 40;

const VERIFICATION_LABELS: Record<string, { label: string; hint: string }> = {
  verified: {
    label: "Verificado por una persona",
    hint: "Una revisión humana confirmó este hallazgo.",
  },
  inferred: {
    label: "Inferido con evidencia",
    hint: "ZENT lo dedujo de pasajes; no es un hecho confirmado.",
  },
  discovered: {
    label: "Detectado, sin verificar",
    hint: "ZENT encontró el pasaje, pero nadie lo revisó todavía.",
  },
  draft: {
    label: "Borrador",
    hint: "Propuesta interna; no debe usarse como hecho.",
  },
  deprecated: {
    label: "Obsoleto",
    hint: "Se conserva por trazabilidad; no es conocimiento vigente.",
  },
  proposed: {
    label: "Propuesta desde pasajes",
    hint: "ZENT la detectó en el texto, pero no es un hecho verificado.",
  },
};

function verificationLabel(status: string) {
  return (
    VERIFICATION_LABELS[status] ?? {
      label: status || "Sin estado",
      hint: "Estado técnico del objeto.",
    }
  );
}

function nodeTone(status: string): string {
  if (status === "verified") return "badge-ok";
  if (status === "inferred") return "badge-pending";
  if (status === "discovered") return "badge-info";
  if (status === "rejected") return "badge-danger";
  return "badge-muted";
}

function canReviewHidden(): boolean {
  const session = loadSession();
  const permissions = session?.permissions ?? [];
  const roles = session?.roles ?? [];
  return (
    permissions.includes("knowledge:write") ||
    roles.some((role) => ["owner", "admin"].includes(role))
  );
}

type ExplorerSource = KnowledgeSourceSummary;
type ExplorerInsightPayload = KnowledgeExplorerInsightPayload;

function DocumentInsightPanel({
  insight,
  sourceId,
  corpusId,
  loading,
  error,
}: {
  insight: ExplorerInsightPayload | null;
  sourceId: string | null;
  corpusId: string | null;
  loading: boolean;
  error: string;
}) {
  const genreLabel: Record<string, string> = {
    narrative: "narrativa",
    technical: "técnica",
    policy: "política",
    legal: "legal",
    tabular: "tabular",
    mixed: "mixta",
    educational: "educativa",
    unknown: "sin género confirmado",
  };
  if (loading) {
    return (
      <Panel className="panel-body" aria-busy="true">
        <Skeleton className="h-24 rounded-md" />
      </Panel>
    );
  }
  if (error) return <ErrorInline message={error} className="mb-0" />;
  if (!insight) {
    return (
      <EmptyState
        icon={BookOpen}
        title="Sin una fuente seleccionada"
        body="Elige un documento para ver qué encontró ZENT, con pasajes y límites de certeza."
      />
    );
  }
  return (
    <div className="flex flex-col gap-4" data-testid="knowledge-document-insight">
      <Panel className="p-4">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div className="min-w-0">
            <p className="eyebrow">Documento</p>
            <h2 className="mt-1 break-words text-h3">Qué contiene este documento</h2>
            <p className="mt-0.5 break-words text-sm font-medium text-text">
              {insight.source.name || "Fuente"}
            </p>
            <p className="prose-measure mt-1 text-sm leading-relaxed text-muted">
              {insight.summary}
            </p>
          </div>
          <div className="flex flex-wrap gap-2 text-[11px] text-faint">
            <span className="badge badge-muted">
              {genreLabel[insight.source.genre] || insight.source.genre}
            </span>
            {insight.source.pages != null && <span>{insight.source.pages} páginas</span>}
            {insight.source.sections != null && (
              <span>{insight.source.sections} secciones</span>
            )}
            {insight.source.tables != null && <span>{insight.source.tables} tablas</span>}
            {(insight.source.document_count ?? 0) > 1 && (
              <span>{insight.source.document_count} documentos</span>
            )}
            {insight.counts.truncated ? (
              <span className="text-warn">lectura parcial</span>
            ) : null}
          </div>
        </div>
        <div className="mt-3 flex flex-wrap gap-x-4 gap-y-1 text-xs text-muted">
          <span>{insight.counts.objects_visible} hallazgos con evidencia</span>
          <span>{insight.counts.objects_total} objetos canónicos históricos</span>
          {typeof insight.counts.passages_available === "number" && (
            <span>{insight.counts.passages_available} pasajes recuperables</span>
          )}
          {typeof insight.counts.revisions === "number" && insight.counts.revisions > 0 && (
            <span>{insight.counts.revisions} en revisión</span>
          )}
          {(insight.counts.objects_not_evaluated ?? 0) > 0 && (
            <span>{insight.counts.objects_not_evaluated} objetos no leídos</span>
          )}
          {(insight.counts.proposals ?? 0) > 0 && (
            <span>{insight.counts.proposals} propuestas desde pasajes</span>
          )}
          {insight.source.genre_confidence != null && (
            <span
              title="Mide la confianza de la clasificación documental. No es el porcentaje del documento que ZENT comprendió."
            >
              Confianza de clasificación{" "}
              {Math.round(insight.source.genre_confidence * 100)}% (no mide
              comprensión)
            </span>
          )}
        </div>
        {sourceId ? (
          <div className="mt-3 flex flex-wrap gap-2">
            <ButtonLink
              to={`/knowledge/ask?${new URLSearchParams({
                ...(corpusId ? { corpus: corpusId } : {}),
                source_ids: sourceId,
              }).toString()}`}
              variant="primary"
              size="sm"
            >
              Preguntar sobre este documento
            </ButtonLink>
            <ButtonLink
              to={`/knowledge/sources/${sourceId}`}
              variant="secondary"
              size="sm"
            >
              Abrir fuente
            </ButtonLink>
          </div>
        ) : null}
        {insight.warnings.length > 0 && (
          <ul className="mt-3 flex flex-col gap-1">
            {insight.warnings.map((warning) => (
              <li
                key={warning.code}
                className="rounded-sm border border-border-soft bg-soft px-2 py-1.5 text-[11px] text-muted"
              >
                {warning.message}
              </li>
            ))}
          </ul>
        )}
      </Panel>

      {(insight.limitations?.length ?? 0) > 0 ? (
        <Panel flat className="p-3" data-testid="document-limitations">
          <details>
            <summary className="cursor-pointer text-xs font-medium text-muted">
              Lo que no podemos asegurar
            </summary>
            <ul className="mt-2 flex list-disc flex-col gap-1 pl-4 text-[11px] leading-relaxed text-muted">
              {insight.limitations!.map((item) => (
                <li key={item}>{item}</li>
              ))}
            </ul>
          </details>
        </Panel>
      ) : null}

      {(insight.structure?.length ?? 0) > 0 ? (
        <Panel className="overflow-hidden" data-testid="document-structure">
          <div className="panel-header">
            <div>
              <h3 className="text-h3">Cómo está organizado</h3>
              <p className="mt-0.5 text-xs text-muted">
                Secciones detectadas en el documento. Los pasajes se abren en la
                fuente original.
              </p>
            </div>
            <span className="mono text-xs text-faint">
              {insight.structure!.length}
            </span>
          </div>
          <ul className="flex flex-col divide-y divide-border-soft">
            {insight.structure!.slice(0, 8).map((section, index) => (
              <li key={`${section.heading}-${index}`} className="px-4 py-2.5">
                <div className="flex flex-wrap items-baseline justify-between gap-2">
                  <p className="text-sm font-medium text-text">
                    {section.heading}
                  </p>
                  {section.page != null ? (
                    <span className="text-[11px] text-faint">
                      página {section.page}
                    </span>
                  ) : null}
                </div>
                {section.excerpt ? (
                  <p className="mt-1 line-clamp-2 text-xs leading-relaxed text-muted">
                    {section.excerpt}
                  </p>
                ) : null}
              </li>
            ))}
          </ul>
        </Panel>
      ) : null}

      {insight.topics.length === 0 ? (
        <Panel className="panel-body flex flex-col gap-3" data-testid="document-insight-empty">
          <div>
            <h3 className="text-h3">No hay temas verificables todavía</h3>
            <p className="prose-measure mt-1 text-sm leading-relaxed text-muted">
              El documento está disponible y sus pasajes se pueden abrir.
              ZENT no encontró conceptos con contexto suficiente para afirmarlos
              como conocimiento. Eso no significa que el documento esté vacío.
            </p>
          </div>
          <ul className="flex flex-col gap-1 text-xs text-muted">
            {insight.source.pages != null && (
              <li>{insight.source.pages} páginas procesadas.</li>
            )}
            {typeof insight.counts.passages_available === "number" && (
              <li>
                {insight.counts.passages_available} pasajes recuperables para
                leer y preguntar.
              </li>
            )}
            <li>
              {insight.counts.objects_total} objetos canónicos históricos se
              conservan fuera de esta vista; no se presentan como temas
              comprendidos.
            </li>
          </ul>
          <div className="flex flex-wrap gap-2">
            {sourceId ? (
              <ButtonLink
                to={`/knowledge/sources/${sourceId}`}
                variant="secondary"
                size="sm"
              >
                Abrir fuente y pasajes
              </ButtonLink>
            ) : null}
          </div>
        </Panel>
      ) : (
        insight.topics.map((topic) => (
          <Panel key={topic.id} className="overflow-hidden">
            <div className="panel-header">
              <div className="min-w-0">
                <h3 className="text-h3">{topic.label}</h3>
                <p className="mt-0.5 text-xs text-muted">{topic.summary}</p>
              </div>
              <span className="mono text-xs text-faint">{topic.count}</span>
            </div>
            <ul className="flex flex-col divide-y divide-border-soft">
              {topic.insights.map((item, index) => (
                <li key={`${topic.id}-${item.object_id ?? item.name}-${index}`} className="p-4">
                  <div className="flex flex-wrap items-start justify-between gap-2">
                    <div className="min-w-0">
                      <p className="break-words text-sm font-medium text-text">
                        {item.name}
                      </p>
                      <p className="mt-1 text-xs leading-relaxed text-muted">
                        {item.claim_text}
                      </p>
                    </div>
                    <span
                      className="badge badge-muted shrink-0"
                      title={verificationLabel(item.verification_state).hint}
                    >
                      {item.uncertainty === "alta"
                        ? "Certeza baja"
                        : verificationLabel(item.verification_state).label}
                    </span>
                  </div>
                  {item.grounded_excerpt ? (
                    <p className="mt-2 line-clamp-3 rounded-sm border border-border-soft bg-soft px-2 py-1.5 text-xs leading-relaxed text-muted">
                      “{item.grounded_excerpt}”
                    </p>
                  ) : (
                    <p className="mt-2 text-[11px] text-warn">
                      Sin pasaje abrible registrado para este hallazgo.
                    </p>
                  )}
                  <div className="mt-2 flex flex-wrap items-center gap-3 text-[11px]">
                    {item.source_locator?.page != null && (
                      <span className="text-faint">
                        página {item.source_locator.page}
                      </span>
                    )}
                    {item.object_id ? (
                      <Link
                        to={`/knowledge/objects/${item.object_id}`}
                        className="text-accent hover:underline"
                      >
                        Ver hallazgo y pasaje
                      </Link>
                    ) : null}
                    {sourceId ? (
                      <Link
                        to={`/knowledge/sources/${sourceId}`}
                        className="text-accent hover:underline"
                      >
                        Abrir fuente
                      </Link>
                    ) : null}
                  </div>
                </li>
              ))}
            </ul>
          </Panel>
        ))
      )}

      {(insight.passages?.length ?? 0) > 0 ? (
        <Panel className="overflow-hidden" data-testid="document-passages">
          <details>
            <summary className="panel-header cursor-pointer list-none">
              <div>
                <h3 className="text-h3">Pasajes que puedes abrir</h3>
                <p className="mt-0.5 text-xs text-muted">
                  Extractos del documento para verificar o preguntar. No son
                  temas verificados.
                </p>
              </div>
              <span className="mono text-xs text-faint">
                {insight.passages!.length}
              </span>
            </summary>
            <ul className="flex flex-col divide-y divide-border-soft">
              {insight.passages!.slice(0, 6).map((passage, index) => (
                <li key={`${passage.passage_id ?? index}`} className="px-4 py-3">
                  <p className="line-clamp-3 text-xs leading-relaxed text-muted">
                    “{passage.excerpt}”
                  </p>
                  <div className="mt-1.5 flex flex-wrap items-center gap-3 text-[11px] text-faint">
                    {passage.page != null ? <span>página {passage.page}</span> : null}
                    {sourceId ? (
                      <Link
                        to={`/knowledge/sources/${sourceId}`}
                        className="text-accent hover:underline"
                      >
                        Ver en la fuente
                      </Link>
                    ) : null}
                  </div>
                </li>
              ))}
            </ul>
          </details>
        </Panel>
      ) : null}
    </div>
  );
}

function GraphPanel({
  payload,
  focusId,
  onFocus,
  onClearFocus,
}: {
  payload: KnowledgeGraphPayload | null;
  focusId: string | null;
  onFocus: (id: string) => void;
  onClearFocus: () => void;
}) {
  const navigate = useNavigate();
  const [selected, setSelected] = useState<string | null>(null);

  const layout = useMemo(() => {
    if (!payload) return { nodes: [], positions: new Map<string, { x: number; y: number }>() };
    const nodes = [...payload.nodes].sort((a, b) => b.degree - a.degree).slice(0, 80);
    const positions = new Map<string, { x: number; y: number }>();
    const total = Math.max(1, nodes.length);
    nodes.forEach((node, index) => {
      const t = index / total;
      const angle = index * 2.399963229728653 - Math.PI / 2;
      const radius = 8 + Math.sqrt(t) * 40;
      positions.set(node.id, {
        x: 50 + Math.cos(angle) * radius,
        y: 31 + Math.sin(angle) * radius * 0.62,
      });
    });
    return { nodes, positions };
  }, [payload]);

  const selectedNode = layout.nodes.find((node) => node.id === selected) ?? null;
  const verifiedEdges = payload
    ? payload.edges.filter((edge) => edge.status === "verified").length
    : 0;
  const unverifiedEdges = payload ? payload.edges.length - verifiedEdges : 0;
  const selectedEdges = selectedNode
    ? (payload?.edges ?? [])
        .filter(
          (edge) =>
            edge.source === selectedNode.id || edge.target === selectedNode.id,
        )
        .slice(0, 6)
    : [];

  if (!payload) {
    return <Skeleton className="h-[420px] rounded-lg" />;
  }
  if (payload.nodes.length === 0) {
    return (
      <EmptyState
        icon={Graph}
        title="Grafo vacío"
        body="Todavía no hay relaciones entre objetos de conocimiento."
      />
    );
  }

  return (
    <div className="flex flex-col gap-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <p className="text-xs text-muted">
          {payload.counts.nodes} nodos · {payload.counts.edges} relaciones ·{" "}
          {verifiedEdges} verificadas · {unverifiedEdges} sin verificar
          {payload.truncated ? " (vecindario acotado)" : ""} · click para inspeccionar
        </p>
        {focusId && (
          <Button size="sm" variant="ghost" leadingIcon={X} onClick={onClearFocus}>
            Quitar foco
          </Button>
        )}
      </div>
      <div className="overflow-hidden rounded-md border border-border bg-surface">
        <svg
          viewBox="0 0 100 62"
          className="h-[420px] w-full"
          role="img"
          aria-label={`Grafo de conocimiento: ${payload.nodes.length} nodos`}
        >
          {payload.edges.map((edge) => {
            const from = layout.positions.get(edge.source);
            const to = layout.positions.get(edge.target);
            if (!from || !to) return null;
            return (
              <line
                key={edge.id}
                x1={from.x}
                y1={from.y}
                x2={to.x}
                y2={to.y}
                className={cn(
                  "kh-edge",
                  edge.status !== "verified" && "is-unverified",
                )}
                style={{ opacity: 0.12 + Math.min(1, edge.confidence) * 0.32 }}
              >
                <title>
                  {edge.predicate} · {edge.status}
                  {edge.status === "verified"
                    ? ""
                    : " (sin verificar, no es un hecho confirmado)"}
                </title>
              </line>
            );
          })}
          {layout.nodes.map((node) => {
            const position = layout.positions.get(node.id);
            if (!position) return null;
            return (
              <g
                key={node.id}
                transform={`translate(${position.x} ${position.y})`}
                className={cn("kh-node", selected === node.id && "is-selected")}
                role="button"
                tabIndex={0}
                aria-label={`${node.name}, ${node.degree} conexiones`}
                onClick={() => setSelected(selected === node.id ? null : node.id)}
                onDoubleClick={() => onFocus(node.id)}
                onKeyDown={(event) => {
                  if (event.key === "Enter" || event.key === " ") {
                    event.preventDefault();
                    setSelected(selected === node.id ? null : node.id);
                  }
                }}
              >
                <circle
                  r={1.1 + Math.min(2.4, Math.sqrt(node.degree + 1) * 0.5)}
                  className={cn("kh-node-dot", nodeTone(node.status))}
                />
                <title>{`${node.name} · ${objectTypeLabel(node.type)} · ${node.status} · ${node.degree} conexiones`}</title>
              </g>
            );
          })}
        </svg>
      </div>
      {selectedNode && (
        <>
        <div className="kh-pulse-detail">
          <div className="min-w-0">
            <p className="truncate text-sm font-medium text-text">{selectedNode.name}</p>
            <p className="mt-0.5 text-[11px] text-muted">
              {objectTypeLabel(selectedNode.type)} · {verificationLabel(selectedNode.status).label} ·{" "}
              {selectedNode.degree} conexiones · {selectedNode.evidence_count} evidencias
            </p>
          </div>
          <div className="flex shrink-0 gap-2">
            <Button size="sm" variant="secondary" onClick={() => onFocus(selectedNode.id)}>
              Enfocar
            </Button>
            <Button
              size="sm"
              variant="primary"
              onClick={() => navigate(`/knowledge/objects/${selectedNode.id}`)}
            >
              Abrir
            </Button>
          </div>
        </div>
        <div className="rounded-md border border-border-soft bg-soft px-3 py-2">
          <p className="text-[11px] font-medium text-muted">
            Relaciones de este nodo
          </p>
          {selectedEdges.length === 0 ? (
            <p className="mt-1 text-[11px] text-faint">
              Todavía no hay relaciones verificables; puedes abrir los pasajes del
              objeto.
            </p>
          ) : (
            <ul className="mt-1 flex flex-col gap-1">
              {selectedEdges.map((edge) => {
                const outgoing = edge.source === selectedNode.id;
                const otherId = outgoing ? edge.target : edge.source;
                return (
                  <li key={edge.id} className="flex flex-wrap items-center gap-2 text-[11px]">
                    <span className="text-muted">
                      {outgoing ? "hacia" : "desde"} {edge.predicate}{" "}
                      {outgoing ? edge.target : edge.source}
                    </span>
                    <span
                      className={cn(
                        "badge",
                        edge.status === "verified" ? "badge-ok" : "badge-pending",
                      )}
                    >
                      {edge.status === "verified" ? "verificada" : "sin verificar"}
                    </span>
                    <Link
                      to={`/knowledge/objects/${otherId}`}
                      className="text-accent hover:underline"
                    >
                      Ver evidencia
                    </Link>
                  </li>
                );
              })}
            </ul>
          )}
        </div>
        </>
      )}
    </div>
  );
}

export default function KnowledgeExplorerPage() {
  const [params, setParams] = useSearchParams();
  const domain = params.get("domain") ?? "";
  const type = params.get("type") ?? "";
  const status = params.get("status") ?? "";
  const orderBy = params.get("order") ?? "updated_at";
  const view = params.get("view") === "graph" ? "graph" : "list";
  const mode = params.get("mode") === "all" ? "all" : "document";
  const sourceParam = params.get("source") ?? "";
  const focusId = params.get("focus");
  const objectsActive = view === "list" && mode === "all";
  const reviewAllowed = useMemo(() => canReviewHidden(), []);

  const [domains, setDomains] = useState<KnowledgeDomain[]>([]);
  const [items, setItems] = useState<KnowledgeObject[]>([]);
  const [total, setTotal] = useState(0);
  const [offset, setOffset] = useState(0);
  const [query, setQuery] = useState(params.get("q") ?? "");
  const [loading, setLoading] = useState(true);
  const [loadingMore, setLoadingMore] = useState(false);
  const [error, setError] = useState("");
  const [graph, setGraph] = useState<KnowledgeGraphPayload | null>(null);
  const [graphLoading, setGraphLoading] = useState(false);
  const [corpusId, setCorpusId] = useState("");
  const [sources, setSources] = useState<ExplorerSource[]>([]);
  const [sourceId, setSourceId] = useState(sourceParam);
  const [insight, setInsight] = useState<ExplorerInsightPayload | null>(null);
  const [insightError, setInsightError] = useState("");
  const [insightLoading, setInsightLoading] = useState(false);
  const [includeHidden, setIncludeHidden] = useState(false);

  const updateParams = useCallback(
    (patch: Record<string, string | null>, replace = true) => {
      const next = new URLSearchParams(params);
      for (const [key, value] of Object.entries(patch)) {
        if (value == null || value === "") next.delete(key);
        else next.set(key, value);
      }
      setParams(next, { replace });
    },
    [params, setParams]
  );

  const switchToDocument = useCallback(() => {
    setQuery("");
    setIncludeHidden(false);
    updateParams({
      view: null,
      mode: null,
      domain: null,
      type: null,
      status: null,
      order: null,
      q: null,
      focus: null,
    });
  }, [updateParams]);

  const switchToAll = useCallback(() => {
    setQuery("");
    setIncludeHidden(false);
    updateParams({
      view: null,
      mode: "all",
      type: null,
      status: null,
      order: null,
      q: null,
      focus: null,
    });
  }, [updateParams]);

  const switchToGraph = useCallback(() => {
    setQuery("");
    setIncludeHidden(false);
    updateParams({
      view: "graph",
      mode: null,
      type: null,
      status: null,
      order: null,
      q: null,
    });
  }, [updateParams]);

  useEffect(() => {
    let cancelled = false;
    void fetchKnowledgeDomains()
      .then((data) => {
        if (!cancelled) setDomains(data.domains);
      })
      .catch(() => {
        if (!cancelled) setDomains([]);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    let cancelled = false;
    void fetchKnowledgeCorpora()
      .then((data) => {
        if (cancelled) return;
        const list = data.corpora ?? [];
        const selected =
          list.find((item) => item.id === params.get("corpus")) ??
          list.find((item) => item.slug === "principal") ??
          list[0];
        setCorpusId(selected?.id ?? "");
      })
      .catch(() => {
        if (!cancelled) setCorpusId("");
      });
    return () => {
      cancelled = true;
    };
    // `params` cambia al navegar; no debe reabrir la lista en cada tecla.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    if (!corpusId) return;
    let cancelled = false;
    void fetchKnowledgeSources(corpusId)
      .then((data) => {
        if (cancelled) return;
        const list = data.sources ?? [];
        setSources(list);
        setSourceId((current) => {
          if (current && list.some((item) => item.id === current)) return current;
          const ready = list.find((item) =>
            ["indexed", "available", "completed"].includes(item.status),
          );
          return (ready ?? list[0])?.id ?? "";
        });
      })
      .catch(() => {
        if (!cancelled) setSources([]);
      });
    return () => {
      cancelled = true;
    };
  }, [corpusId]);

  useEffect(() => {
    if (!sourceId) {
      setInsight(null);
      return;
    }
    if (sourceId !== sourceParam) {
      updateParams({ source: sourceId }, true);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [sourceId]);

  useEffect(() => {
    if (!corpusId || !sourceId || view !== "list" || mode !== "document") {
      setInsight(null);
      return;
    }
    let cancelled = false;
    setInsightLoading(true);
    setInsightError("");
    void fetchKnowledgeSourceInsight(corpusId, sourceId)
      .then((data) => {
        if (!cancelled) setInsight(data);
      })
      .catch((err) => {
        if (!cancelled) {
          setInsight(null);
          setInsightError(
            err instanceof Error ? err.message : "No pudimos leer este documento.",
          );
        }
      })
      .finally(() => {
        if (!cancelled) setInsightLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [corpusId, sourceId, view, mode]);

  const loadObjects = useCallback(
    async (nextOffset: number, append: boolean) => {
      if (append) setLoadingMore(true);
      else setLoading(true);
      setError("");
      try {
        const data = await fetchKnowledgeObjects({
          domain: domain || undefined,
          type: type || undefined,
          status: status || undefined,
          source_id: undefined,
          q: query.trim() || undefined,
          order_by: orderBy,
          limit: PAGE_SIZE,
          offset: nextOffset,
          exclude_hidden: !includeHidden,
        });
        setItems((previous) => (append ? [...previous, ...data.items] : data.items));
        setTotal(data.total);
        setOffset(nextOffset);
      } catch (err) {
        setItems([]);
        setError(err instanceof Error ? err.message : "No pudimos leer el conocimiento.");
      } finally {
        setLoading(false);
        setLoadingMore(false);
      }
    },
    [domain, type, status, query, orderBy, includeHidden]
  );

  useEffect(() => {
    if (!objectsActive) {
      setLoading(false);
      setItems([]);
      setTotal(0);
      setOffset(0);
      return;
    }
    void loadObjects(0, false);
  }, [loadObjects, objectsActive]);

  useEffect(() => {
    if (view !== "graph") return;
    let cancelled = false;
    setGraphLoading(true);
    void fetchKnowledgeGraph({
      focus_id: focusId ?? undefined,
      domains: domain || undefined,
      source_id: sourceId || undefined,
      exclude_hidden: true,
      limit_nodes: 80,
      limit_edges: 160,
    })
      .then((data) => {
        if (!cancelled) setGraph(data);
      })
      .catch(() => {
        if (!cancelled) setGraph(null);
      })
      .finally(() => {
        if (!cancelled) setGraphLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [view, focusId, domain, sourceId]);

  const selectedDomain = domains.find((item) => item.name === domain) ?? null;
  const topics = selectedDomain?.by_type ?? [];
  const showTopics =
    view === "list" &&
    mode === "all" &&
    Boolean(domain) &&
    !type &&
    !query.trim();

  return (
    <KnowledgeLayout>
      <header className="mb-5 flex flex-wrap items-end justify-between gap-3">
        <div className="min-w-0">
          <h1 className="text-h1">Qué encontramos en tus documentos</h1>
          <p className="prose-measure mt-1.5 text-sm leading-relaxed text-muted">
            Elige un documento, revisa qué entendió ZENT y abre el pasaje que
            sustenta cada hallazgo. Una interpretación no es un hecho verificado.
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <Button
            size="sm"
            variant={view === "list" && mode === "document" ? "secondary" : "ghost"}
            leadingIcon={BookOpen}
            onClick={switchToDocument}
          >
            Por documento
          </Button>
          <Button
            size="sm"
            variant={view === "list" && mode === "all" ? "secondary" : "ghost"}
            leadingIcon={ListBullets}
            onClick={switchToAll}
          >
            Todos los hallazgos
          </Button>
          <Button
            size="sm"
            variant={view === "graph" ? "secondary" : "ghost"}
            leadingIcon={Graph}
            onClick={switchToGraph}
          >
            Grafo
          </Button>
          <ButtonLink to="/knowledge/map" size="sm" variant="primary" leadingIcon={Graph}>
            Knowledge Map
          </ButtonLink>
        </div>
      </header>

      <div
        className={cn(
          "grid gap-4",
          mode === "all" && "lg:grid-cols-[240px_minmax(0,1fr)]"
        )}
      >
        {mode === "all" ? (
        <aside className="flex flex-col gap-2">
          <Panel className="overflow-hidden">
            <div className="panel-header py-2.5">
              <h2 className="eyebrow">Dominios</h2>
            </div>
            <ul className="flex flex-col p-1.5">
              <li>
                <button
                  type="button"
                  className={cn("kh-domain-item", !domain && "is-active")}
                  onClick={() => updateParams({ domain: null })}
                >
                  <span className="min-w-0 flex-1 truncate text-left">Todos</span>
                  <span className="mono text-[11px] text-faint">{total}</span>
                </button>
              </li>
              {domains
                .filter((item) => item.objects > 0)
                .map((item) => (
                  <li key={item.name}>
                    <button
                      type="button"
                      className={cn(
                        "kh-domain-item",
                        domain === item.name && "is-active"
                      )}
                      onClick={() => updateParams({ domain: item.name })}
                    >
                      <span className="min-w-0 flex-1 truncate text-left">{item.name}</span>
                      <span className="mono text-[11px] text-faint">{item.objects}</span>
                    </button>
                  </li>
                ))}
            </ul>
          </Panel>
        </aside>
        ) : null}

        <div className="flex min-w-0 flex-col gap-4">
          <Panel flat className="p-3">
            <div className="flex flex-col gap-2 xl:flex-row xl:items-center">
              {objectsActive ? (
              <div className="relative min-w-0 flex-1">
                <MagnifyingGlass
                  size={14}
                  className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-faint"
                  aria-hidden
                />
                <input
                  className="input pl-8"
                  placeholder="Filtrar objetos por nombre…"
                  value={query}
                  onChange={(event) => setQuery(event.target.value)}
                  aria-label="Filtrar objetos"
                />
              </div>
              ) : null}
              <div className="flex flex-wrap gap-2">
                {view === "list" && mode === "document" ? (
                <Select
                  aria-label="Documento"
                  value={sourceId}
                  onChange={(event) => {
                    setSourceId(event.target.value);
                    updateParams({ source: event.target.value });
                  }}
                  className="min-h-9 w-[210px]"
                  disabled={sources.length === 0}
                >
                  {sources.length === 0 ? (
                    <option value="">Sin fuentes</option>
                  ) : null}
                  {sources.map((source) => (
                    <option key={source.id} value={source.id}>
                      {source.name}
                    </option>
                  ))}
                </Select>
                ) : null}
                {objectsActive ? (
                <>
                <Select
                  aria-label="Tipo de conocimiento"
                  value={type}
                  onChange={(event) => updateParams({ type: event.target.value })}
                  className="min-h-9 w-[170px]"
                >
                  {TYPE_OPTIONS.map((option) => (
                    <option key={option.value} value={option.value}>
                      {option.label}
                    </option>
                  ))}
                </Select>
                <Select
                  aria-label="Estado"
                  value={status}
                  onChange={(event) => updateParams({ status: event.target.value })}
                  className="min-h-9 w-[150px]"
                >
                  {STATUS_OPTIONS.map((option) => (
                    <option key={option.value} value={option.value}>
                      {option.label}
                    </option>
                  ))}
                </Select>
                <Select
                  aria-label="Orden"
                  value={orderBy}
                  onChange={(event) => updateParams({ order: event.target.value })}
                  className="min-h-9 w-[150px]"
                >
                  {ORDER_OPTIONS.map((option) => (
                    <option key={option.value} value={option.value}>
                      {option.label}
                    </option>
                  ))}
                </Select>
                </>
                ) : null}
              </div>
            </div>
          </Panel>

          {mode === "all" && (domain || type) && (
            <nav
              className="flex flex-wrap items-center gap-2 text-xs"
              aria-label="Ruta de exploración"
            >
              <span className="text-faint">Ruta:</span>
              <button
                type="button"
                className="kh-crumb"
                onClick={() => updateParams({ domain: null, type: null })}
              >
                Todos
              </button>
              {domain && (
                <>
                  <span className="text-ghost" aria-hidden>
                    /
                  </span>
                  <button
                    type="button"
                    className={cn("kh-crumb", !type && "is-current")}
                    onClick={() => updateParams({ type: null })}
                  >
                    {domain}
                  </button>
                </>
              )}
              {type && (
                <>
                  <span className="text-ghost" aria-hidden>
                    /
                  </span>
                  <span className="kh-crumb is-current">{objectTypeLabel(type)}</span>
                </>
              )}
            </nav>
          )}

          {error && <ErrorInline message={error} className="mb-0" />}

          {view === "graph" ? (
            <Panel className="panel-body">
              <GraphPanel
                payload={graphLoading && !graph ? null : graph}
                focusId={focusId}
                onFocus={(id) => updateParams({ focus: id })}
                onClearFocus={() => updateParams({ focus: null })}
              />
            </Panel>
          ) : mode === "document" ? (
            <DocumentInsightPanel
              insight={insight}
              sourceId={sourceId || null}
              corpusId={corpusId || null}
              loading={insightLoading}
              error={insightError}
            />
          ) : showTopics ? (
            <Panel className="overflow-hidden" data-testid="knowledge-topics">
              <div className="panel-header">
                <div className="min-w-0">
                  <h2 className="text-h3">Temas de {domain}</h2>
                  <p className="mt-0.5 text-xs text-muted">
                    Tipos de conocimiento que ZENT aprendió en este dominio.
                  </p>
                </div>
                <Button
                  size="sm"
                  variant="ghost"
                  onClick={() => updateParams({ domain: null, type: null })}
                >
                  Todos los dominios
                </Button>
              </div>
              <div className="panel-body">
                {topics.length === 0 ? (
                  <div className="flex flex-col items-start gap-2">
                    <p className="text-sm text-muted">
                      Este dominio todavía no tiene temas de negocio; sus objetos
                      son soporte (tablas, columnas y documentos).
                    </p>
                    <Button
                      size="sm"
                      variant="secondary"
                      onClick={() => updateParams({ type: null })}
                    >
                      Ver todos los objetos
                    </Button>
                  </div>
                ) : (
                  <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
                    {topics.map((topic) => {
                      const coverage =
                        topic.total > 0 ? (topic.verified / topic.total) * 100 : 0;
                      return (
                        <button
                          key={topic.type}
                          type="button"
                          className="kh-topic-card"
                          onClick={() => updateParams({ type: topic.type })}
                        >
                          <span className="flex items-center justify-between gap-2">
                            <span className="text-sm font-medium text-text">
                              {objectTypeLabel(topic.type)}
                            </span>
                            <span className="mono text-xs tabular-nums text-muted">
                              {topic.total}
                            </span>
                          </span>
                          <span className="mt-2 block h-1 overflow-hidden rounded-full bg-track">
                            <span
                              className={cn(
                                "block h-full rounded-full",
                                coverage >= 70
                                  ? "bg-ok"
                                  : coverage >= 40
                                    ? "bg-warn"
                                    : "bg-danger"
                              )}
                              style={{ width: `${Math.max(3, Math.min(100, coverage))}%` }}
                            />
                          </span>
                          <span className="mt-1 block text-[11px] text-faint">
                            {Math.round(coverage)}% verificado
                          </span>
                        </button>
                      );
                    })}
                    <button
                      type="button"
                      className="kh-topic-card is-all"
                      onClick={() => updateParams({ type: null })}
                    >
                      <span className="text-sm font-medium text-text">
                        Todos los objetos
                      </span>
                      <span className="mt-1 block text-[11px] text-faint">
                        Incluye tablas, columnas y documentos de soporte
                      </span>
                    </button>
                  </div>
                )}
              </div>
            </Panel>
          ) : (
            <div className="flex flex-col gap-3">
              <Panel flat className="p-3" data-testid="technical-view-banner">
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <div>
                    <p className="text-sm font-medium text-text">Vista técnica</p>
                    <p className="mt-0.5 text-xs text-muted">
                      Objetos canónicos con IDs y estados. Pueden incluir
                      registros históricos que no son temas comprendidos.
                    </p>
                  </div>
                  <div className="flex flex-wrap items-center gap-3 text-xs text-muted">
                    <span>{total} objetos canónicos</span>
                    {reviewAllowed ? (
                      <label className="flex items-center gap-1.5">
                        <input
                          type="checkbox"
                          checked={includeHidden}
                          onChange={(event) => setIncludeHidden(event.target.checked)}
                        />
                        Incluir ocultos en revisión
                      </label>
                    ) : null}
                  </div>
                </div>
              </Panel>
            <Panel className="overflow-hidden">
              {loading ? (
                <div className="flex flex-col gap-2 p-4" aria-busy="true">
                  {[0, 1, 2, 3, 4].map((i) => (
                    <Skeleton key={i} className="h-12 rounded-md" />
                  ))}
                </div>
              ) : items.length === 0 ? (
                <EmptyState
                  icon={MagnifyingGlass}
                  title="Sin objetos con estos filtros"
                  body="Prueba otro dominio, tipo o término. Si ZENT todavía no aprendió de esta área, aparecerá cuando conectes una fuente."
                />
              ) : (
                <>
                  <ul className="flex flex-col divide-y divide-border-soft">
                    {items.map((item) => (
                      <li key={item.id}>
                        <Link
                          to={`/knowledge/objects/${item.id}`}
                          className="flex items-center gap-3 px-4 py-3 transition-colors duration-150 hover:bg-soft/50"
                        >
                          <span className="min-w-0 flex-1">
                            <span className="flex items-center gap-2">
                              <span className="truncate text-sm font-medium text-text">
                                {item.display_name || item.name}
                              </span>
                              <span
                                className={cn("badge shrink-0", statusTone(item.status))}
                                title={verificationLabel(item.status).hint}
                              >
                                {verificationLabel(item.status).label}
                              </span>
                            </span>
                            <span className="mt-0.5 flex flex-wrap items-center gap-x-2 text-[11px] text-faint">
                              <span>{objectTypeLabel(item.type)}</span>
                              {item.domain && <span>{item.domain}</span>}
                              <span>{item.evidence_count} evidencias</span>
                              <span>actualizado {timeAgo(item.updated_at)}</span>
                            </span>
                          </span>
                          {item.confidence != null && (
                            <KnowledgeConfidenceBadge confidence={item.confidence} compact />
                          )}
                          <ArrowRight size={13} className="shrink-0 text-ghost" aria-hidden />
                        </Link>
                      </li>
                    ))}
                  </ul>
                  <div className="flex items-center justify-between gap-3 border-t border-border px-4 py-3">
                    <span className="text-xs text-muted">
                      {items.length} de {total} objetos
                      {items.length < total ? " · resultados parciales" : ""}
                    </span>
                    {items.length < total && (
                      <Button
                        size="sm"
                        variant="secondary"
                        disabled={loadingMore}
                        onClick={() => void loadObjects(offset + PAGE_SIZE, true)}
                      >
                        {loadingMore ? "Cargando…" : "Cargar más"}
                      </Button>
                    )}
                  </div>
                </>
              )}
            </Panel>
            </div>
          )}
        </div>
      </div>
    </KnowledgeLayout>
  );
}
