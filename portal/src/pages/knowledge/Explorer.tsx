// =============================================================================
// Explorador — Dominio → Tipo → Objeto → Hecho → Evidencia → Fuente
// =============================================================================
import { useCallback, useEffect, useMemo, useState } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import {
  ArrowRight,
  Graph,
  ListBullets,
  MagnifyingGlass,
  X,
} from "@phosphor-icons/react";
import {
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
  fetchKnowledgeDomains,
  fetchKnowledgeGraph,
  fetchKnowledgeObjects,
  objectTypeLabel,
  statusTone,
  type KnowledgeDomain,
  type KnowledgeGraphPayload,
  type KnowledgeObject,
} from "../../lib/knowledgeModel";
import { timeAgo } from "../../lib/format";

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
          {payload.counts.nodes} nodos · {payload.counts.edges} relaciones
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
                className="kh-edge"
                style={{ opacity: 0.12 + Math.min(1, edge.confidence) * 0.32 }}
              >
                <title>{edge.predicate}</title>
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
                  className="kh-node-dot"
                />
                <title>{`${node.name} · ${objectTypeLabel(node.type)} · ${node.degree} conexiones`}</title>
              </g>
            );
          })}
        </svg>
      </div>
      {selectedNode && (
        <div className="kh-pulse-detail">
          <div className="min-w-0">
            <p className="truncate text-sm font-medium text-text">{selectedNode.name}</p>
            <p className="mt-0.5 text-[11px] text-muted">
              {objectTypeLabel(selectedNode.type)} · {selectedNode.degree} conexiones ·{" "}
              {selectedNode.evidence_count} evidencias
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
  const focusId = params.get("focus");

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
          q: query.trim() || undefined,
          order_by: orderBy,
          limit: PAGE_SIZE,
          offset: nextOffset,
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
    [domain, type, status, query, orderBy]
  );

  useEffect(() => {
    void loadObjects(0, false);
  }, [loadObjects]);

  useEffect(() => {
    if (view !== "graph") return;
    let cancelled = false;
    setGraphLoading(true);
    void fetchKnowledgeGraph({
      focus_id: focusId ?? undefined,
      domains: domain || undefined,
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
  }, [view, focusId, domain]);

  const selectedDomain = domains.find((item) => item.name === domain) ?? null;
  const topics = selectedDomain?.by_type ?? [];
  const showTopics = view === "list" && Boolean(domain) && !type && !query.trim();

  return (
    <KnowledgeLayout>
      <header className="mb-5 flex flex-wrap items-end justify-between gap-3">
        <div className="min-w-0">
          <h1 className="text-h1">Explorador</h1>
          <p className="prose-measure mt-1.5 text-sm leading-relaxed text-muted">
            Recorre el conocimiento como está organizado: dominio, tipo, objeto,
            hechos, evidencia y fuente.
          </p>
        </div>
        <div className="flex items-center gap-2">
          <Button
            size="sm"
            variant={view === "list" ? "secondary" : "ghost"}
            leadingIcon={ListBullets}
            onClick={() => updateParams({ view: null, focus: null })}
          >
            Lista
          </Button>
          <Button
            size="sm"
            variant={view === "graph" ? "secondary" : "ghost"}
            leadingIcon={Graph}
            onClick={() => updateParams({ view: "graph" })}
          >
            Grafo
          </Button>
          <ButtonLink to="/knowledge/map" size="sm" variant="primary" leadingIcon={Graph}>
            Knowledge Map
          </ButtonLink>
        </div>
      </header>

      <div className="grid gap-4 lg:grid-cols-[240px_minmax(0,1fr)]">
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

        <div className="flex min-w-0 flex-col gap-4">
          <Panel flat className="p-3">
            <div className="flex flex-col gap-2 xl:flex-row xl:items-center">
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
              <div className="flex flex-wrap gap-2">
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
              </div>
            </div>
          </Panel>

          {(domain || type) && (
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
                              <span className={cn("badge shrink-0", statusTone(item.status))}>
                                {item.status}
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
          )}
        </div>
      </div>
    </KnowledgeLayout>
  );
}
