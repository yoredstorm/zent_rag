// =============================================================================
// Knowledge Map — /knowledge/map (FASE 33F)
// =============================================================================
// Grafo real del negocio aprendido: entidades, relaciones, métricas, reglas,
// dimensiones, sinónimos y preguntas verificadas. Nodos y aristas provienen
// de /graph (PostgreSQL): confianza, provenance, fuente y validación reales.
// =============================================================================
import { Graph, MagnifyingGlass } from "@phosphor-icons/react";
import { useCallback, useEffect, useMemo, useState } from "react";
import { KnowledgeLayout } from "../../components/KnowledgeLayout";
import { KnowledgeGraphCanvas } from "../../components/knowledgeLearning/KnowledgeGraphCanvas";
import { KnowledgeNodeDetail } from "../../components/knowledgeLearning/KnowledgeNodeDetail";
import {
  EmptyState,
  ErrorInline,
  PageHeader,
  SkeletonBlock,
} from "../../components/ui";
import { useAuth } from "../../auth";
import {
  NODE_TYPE_LABELS,
  computeLayout,
  fetchKnowledgeGraph,
  type GraphEdge,
  type GraphNode,
  type GraphNodeType,
} from "../../lib/knowledgeGraph";
import {
  fetchLearningSources,
  fetchQuestions,
  type SourceLearning,
} from "../../lib/knowledgeLearning";

const ALL_TYPES: GraphNodeType[] = [
  "datasource",
  "entity",
  "field",
  "metric",
  "dimension",
  "rule",
  "synonym",
  "verified_question",
];

const DEFAULT_TYPES = new Set<GraphNodeType>([
  "datasource",
  "entity",
  "metric",
  "dimension",
  "rule",
  "synonym",
  "verified_question",
]);

const PROVENANCES = ["", "OBSERVED", "INFERRED", "APPROVED", "REJECTED"];

export default function KnowledgeMapPage() {
  const { session } = useAuth();
  const [sources, setSources] = useState<SourceLearning[]>([]);
  const [selectedSourceId, setSelectedSourceId] = useState("");
  const [graph, setGraph] = useState<{ nodes: GraphNode[]; edges: GraphEdge[] } | null>(
    null
  );
  const [enabledTypes, setEnabledTypes] = useState<Set<GraphNodeType>>(DEFAULT_TYPES);
  const [showFields, setShowFields] = useState(false);
  const [provenance, setProvenance] = useState("");
  const [search, setSearch] = useState("");
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [detailQuestions, setDetailQuestions] = useState<string[]>([]);
  const [loadingQuestions, setLoadingQuestions] = useState(false);

  useEffect(() => {
    if (!session) return;
    fetchLearningSources()
      .then((items) => {
        setSources(items || []);
        if (items?.[0]) setSelectedSourceId(items[0].source_id);
      })
      .catch(() => setSources([]));
  }, [session]);

  const loadGraph = useCallback(async (sourceId: string) => {
    setLoading(true);
    setError("");
    try {
      const data = await fetchKnowledgeGraph({ sourceId, limitNodes: 200, limitEdges: 500 });
      setGraph({ nodes: data.nodes, edges: data.edges });
      setSelectedId(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : "No se pudo cargar el mapa");
      setGraph(null);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    if (selectedSourceId) void loadGraph(selectedSourceId);
  }, [selectedSourceId, loadGraph]);

  const positioned = useMemo(
    () => (graph ? computeLayout(graph.nodes, graph.edges) : []),
    [graph]
  );
  const labelOf = useMemo(() => {
    const map = new Map<string, string>();
    for (const node of positioned) map.set(node.id, node.label);
    return (nodeId: string) => map.get(nodeId) || nodeId.slice(0, 16);
  }, [positioned]);

  // Filtros: tipos + provenance + búsqueda (nodos visibles; el resto se atenúa).
  const effectiveTypes = useMemo(() => {
    const types = new Set(enabledTypes);
    if (showFields) types.add("field");
    return types;
  }, [enabledTypes, showFields]);

  const visibleIds = useMemo(() => {
    const needle = search.trim().toLowerCase();
    const visible = new Set<string>();
    for (const node of positioned) {
      if (!effectiveTypes.has(node.type)) continue;
      if (provenance && node.provenance !== provenance) continue;
      if (
        needle &&
        !node.label.toLowerCase().includes(needle) &&
        !(node.description || "").toLowerCase().includes(needle) &&
        !String(node.metadata?.table || "").toLowerCase().includes(needle)
      ) {
        continue;
      }
      visible.add(node.id);
    }
    return visible;
  }, [positioned, effectiveTypes, provenance, search]);

  const visibleEdges = useMemo(
    () =>
      (graph?.edges || []).filter(
        (edge) => visibleIds.has(edge.from) && visibleIds.has(edge.to)
      ),
    [graph, visibleIds]
  );

  useEffect(() => {
    if (!selectedId || !graph) return;
    const node = positioned.find((item) => item.id === selectedId);
    if (!node || node.type !== "entity") {
      setDetailQuestions([]);
      return;
    }
    setLoadingQuestions(true);
    fetchQuestions({ entity_id: selectedId.replace("entity:", ""), limit: 20 })
      .then((data) => setDetailQuestions((data.questions || []).map((q) => q.title)))
      .catch(() => setDetailQuestions([]))
      .finally(() => setLoadingQuestions(false));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedId, graph]);

  const selectedNode = positioned.find((node) => node.id === selectedId) || null;

  return (
    <KnowledgeLayout>
      <div data-testid="map-page">
        <PageHeader
          title="Knowledge Map"
          subtitle="El modelo de negocio que Zent aprendió: entidades, relaciones, confianza, provenance y estado de validación."
          actions={
            <>
              <label className="sr-only" htmlFor="map-source">Fuente</label>
              <select
                id="map-source"
                className="field min-h-9"
                value={selectedSourceId}
                onChange={(event) => setSelectedSourceId(event.target.value)}
              >
                {sources.length === 0 && <option value="">Sin fuentes</option>}
                {sources.map((source) => (
                  <option key={source.source_id} value={source.source_id}>
                    {(source.engine || "Fuente")} · {source.source_id.slice(0, 8)}
                  </option>
                ))}
              </select>
            </>
          }
        />

        {error && <ErrorInline>{error}</ErrorInline>}

        {loading ? (
          <SkeletonBlock rows={6} />
        ) : !graph || positioned.length === 0 ? (
          <div className="panel">
            <EmptyState
              icon={Graph}
              title="Mapa vacío"
              body="Ejecuta un aprendizaje para que Zent descubra entidades y relaciones."
            />
          </div>
        ) : (
          <>
            <div className="panel mb-3">
              <div className="flex flex-wrap items-center gap-3">
                <div className="relative min-w-52 flex-1">
                  <MagnifyingGlass
                    size={14}
                    aria-hidden
                    className="pointer-events-none absolute left-2.5 top-1/2 -translate-y-1/2 text-faint"
                  />
                  <input
                    className="field h-8 w-full pl-8"
                    placeholder="Buscar entidad, tabla o descripción…"
                    aria-label="Buscar en el mapa"
                    data-testid="map-search"
                    value={search}
                    onChange={(event) => setSearch(event.target.value)}
                  />
                </div>
                <label className="flex items-center gap-1.5 text-[12px] text-muted">
                  <input
                    type="checkbox"
                    className="accent-[var(--color-accent)]"
                    checked={showFields}
                    data-testid="map-show-fields"
                    onChange={(event) => setShowFields(event.target.checked)}
                  />
                  Mostrar campos
                </label>
                <label className="flex items-center gap-1.5 text-[12px] text-muted">
                  Provenance
                  <select
                    className="field h-8"
                    value={provenance}
                    onChange={(event) => setProvenance(event.target.value)}
                  >
                    {PROVENANCES.map((value) => (
                      <option key={value === "" ? "all" : value} value={value}>
                        {value === "" ? "Todos" : value}
                      </option>
                    ))}
                  </select>
                </label>
                <span className="text-[11px] text-faint">
                  {visibleIds.size} de {positioned.length} nodos · {visibleEdges.length} aristas
                </span>
              </div>
              <div className="mt-2 flex flex-wrap items-center gap-1.5" role="group" aria-label="Tipos de nodo">
                {ALL_TYPES.filter((type) => type !== "field").map((type) => {
                  const checked = enabledTypes.has(type);
                  return (
                    <button
                      key={type}
                      type="button"
                      className={`btn min-h-7 px-2 py-0.5 text-[11px] ${
                        checked ? "btn-secondary" : "btn-ghost"
                      }`}
                      aria-pressed={checked}
                      data-testid={`map-type-${type}`}
                      onClick={() =>
                        setEnabledTypes((current) => {
                          const next = new Set(current);
                          if (next.has(type)) next.delete(type);
                          else next.add(type);
                          return next;
                        })
                      }
                    >
                      {NODE_TYPE_LABELS[type]}
                    </button>
                  );
                })}
              </div>
            </div>

            <div className="grid gap-3 lg:grid-cols-[1fr_300px]">
              <div className="min-h-[560px]">
                <KnowledgeGraphCanvas
                  nodes={positioned}
                  edges={visibleEdges}
                  selectedId={selectedId}
                  visibleIds={visibleIds}
                  onSelect={(nodeId) => setSelectedId(nodeId)}
                />
              </div>
              <KnowledgeNodeDetail
                node={selectedNode}
                edges={visibleEdges}
                labelOf={labelOf}
                openQuestions={detailQuestions}
                loadingQuestions={loadingQuestions}
              />
            </div>

            <p className="mt-3 text-[11px] text-faint">
              Máximo de nodos cargados: 200 por fuente. Usa búsqueda y filtros para enfocar el mapa.
            </p>
          </>
        )}
      </div>
    </KnowledgeLayout>
  );
}