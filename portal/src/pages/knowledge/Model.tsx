import {
  ArrowsOut,
  Brain,
  Graph,
  ListBullets,
  MagnifyingGlass,
  X,
} from "@phosphor-icons/react";
import { useCallback, useEffect, useMemo, useState } from "react";
import { useSearchParams } from "react-router-dom";
import {
  Button,
  cn,
  Drawer,
  EmptyState,
  ErrorInline,
  Panel,
  PageHeader,
  Select,
  Skeleton,
} from "../../components/ui";
import { KnowledgeLayout } from "../../components/KnowledgeLayout";
import { KnowledgeConfidenceBadge } from "../../components/knowledgeLearning/KnowledgeConfidenceBadge";
import { KNOWLEDGE_HEADINGS } from "../../lib/knowledgeNav";
import {
  fetchKnowledgeGraph,
  fetchKnowledgeObject,
  fetchKnowledgeObjects,
  objectTypeLabel,
  statusTone,
  verifyKnowledgeObject,
  type KnowledgeGraphPayload,
  type KnowledgeObject,
  type KnowledgeObjectDetail,
} from "../../lib/knowledgeModel";
import { fmtDateTime, fmtNum } from "../../lib/format";

type ViewMode = "explorer" | "table" | "graph";

const VIEW_TABS: { id: ViewMode; label: string; icon: typeof Brain }[] = [
  { id: "explorer", label: "Explorer", icon: Brain },
  { id: "table", label: "Tabla", icon: ListBullets },
  { id: "graph", label: "Grafo", icon: Graph },
];

const TYPE_FILTERS: { value: string; label: string }[] = [
  { value: "", label: "Todo" },
  { value: "entity", label: "Entidades" },
  { value: "attribute", label: "Atributos" },
  { value: "relationship", label: "Relaciones" },
  { value: "business_rule", label: "Reglas" },
  { value: "metric", label: "Métricas" },
  { value: "term", label: "Términos" },
  { value: "process", label: "Procesos" },
  { value: "domain", label: "Dominios" },
];

function ObjectMeta({ item }: { item: KnowledgeObject }) {
  return (
    <span className="flex flex-wrap items-center gap-1.5">
      <span className="badge badge-muted">{objectTypeLabel(item.type)}</span>
      <span className={cn("badge", statusTone(item.status))}>{item.status}</span>
      {item.confidence != null && (
        <KnowledgeConfidenceBadge confidence={item.confidence} compact />
      )}
      {item.domain && <span className="text-xs text-muted">{item.domain}</span>}
    </span>
  );
}

function GraphView({
  payload,
  onSelect,
  onExpand,
  selectedId,
}: {
  payload: KnowledgeGraphPayload | null;
  onSelect: (id: string) => void;
  onExpand: (id: string) => void;
  selectedId: string | null;
}) {
  const [zoom, setZoom] = useState(1);
  const layout = useMemo(() => {
    if (!payload) return { nodes: [], positions: new Map<string, { x: number; y: number }>() };
    const width = 1000;
    const height = 640;
    const nodes = [...payload.nodes].sort((a, b) => b.degree - a.degree);
    const positions = new Map<string, { x: number; y: number }>();
    const radius = Math.min(width, height) * 0.38;
    nodes.forEach((node, index) => {
      const angle = (index / Math.max(nodes.length, 1)) * Math.PI * 2;
      positions.set(node.id, {
        x: width / 2 + Math.cos(angle) * radius,
        y: height / 2 + Math.sin(angle) * radius * 0.85,
      });
    });
    return { nodes, positions, width, height };
  }, [payload]);

  if (!payload) return null;
  if (payload.nodes.length === 0) {
    return (
      <EmptyState
        icon={Graph}
        title="Grafo vacío"
        body="Todavía no hay relaciones entre objetos de conocimiento."
      />
    );
  }
  const { nodes, positions } = layout;
  const viewWidth = 1000 / zoom;
  const viewHeight = 640 / zoom;

  return (
    <div className="flex flex-col gap-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <p className="text-xs text-muted">
          {payload.counts.nodes} nodos · {payload.counts.edges} aristas
          {payload.truncated ? " (truncado)" : ""} · click para abrir, doble click para
          expandir vecinos
        </p>
        <div className="flex gap-1">
          <Button size="sm" variant="ghost" onClick={() => setZoom((z) => Math.max(0.6, z - 0.2))}>
            −
          </Button>
          <Button size="sm" variant="ghost" onClick={() => setZoom((z) => Math.min(2.4, z + 0.2))}>
            +
          </Button>
        </div>
      </div>
      <div className="overflow-hidden rounded-lg border border-border bg-surface">
        <svg
          viewBox={`${500 - viewWidth / 2} ${320 - viewHeight / 2} ${viewWidth} ${viewHeight}`}
          className="h-[480px] w-full"
          role="img"
          aria-label="Grafo de conocimiento"
        >
          {payload.edges.map((edge) => {
            const from = positions.get(edge.source);
            const to = positions.get(edge.target);
            if (!from || !to) return null;
            return (
              <line
                key={edge.id}
                x1={from.x}
                y1={from.y}
                x2={to.x}
                y2={to.y}
                stroke="var(--color-border)"
                strokeWidth={1}
              />
            );
          })}
          {nodes.map((node) => {
            const position = positions.get(node.id);
            if (!position) return null;
            const radius = node.type === "entity" ? 16 : node.type === "table" ? 12 : 9;
            const selected = node.id === selectedId;
            return (
              <g
                key={node.id}
                transform={`translate(${position.x}, ${position.y})`}
                className="cursor-pointer"
                onClick={() => onSelect(node.id)}
                onDoubleClick={() => onExpand(node.id)}
              >
                <circle
                  r={radius}
                  fill={selected ? "var(--color-accent)" : "var(--color-surface)"}
                  stroke={selected ? "var(--color-accent)" : "var(--color-border-strong)"}
                  strokeWidth={2}
                />
                <text
                  y={radius + 12}
                  textAnchor="middle"
                  className="fill-[var(--color-text)] text-[10px]"
                >
                  {node.name.length > 22 ? `${node.name.slice(0, 20)}…` : node.name}
                </text>
              </g>
            );
          })}
        </svg>
      </div>
    </div>
  );
}

function DetailSection({
  title,
  count,
  children,
  empty,
}: {
  title: string;
  count?: number;
  children: React.ReactNode;
  empty?: string;
}) {
  return (
    <section className="border-t border-border px-5 py-4">
      <h3 className="eyebrow mb-2">
        {title}
        {count != null ? ` · ${count}` : ""}
      </h3>
      {count === 0 && empty ? <p className="text-sm text-muted">{empty}</p> : children}
    </section>
  );
}

export default function KnowledgeModelPage() {
  const [params, setParams] = useSearchParams();
  const view = (params.get("view") as ViewMode) || "explorer";
  const query = params.get("q") || "";
  const type = params.get("type") || "";
  const domain = params.get("domain") || "";
  const status = params.get("status") || "";
  const focusId = params.get("focus");

  const [searchDraft, setSearchDraft] = useState(query);
  const [objects, setObjects] = useState<KnowledgeObject[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [graph, setGraph] = useState<KnowledgeGraphPayload | null>(null);
  const [detail, setDetail] = useState<KnowledgeObjectDetail | null>(null);
  const [detailError, setDetailError] = useState("");
  const [verifyState, setVerifyState] = useState("");
  const [domains, setDomains] = useState<string[]>([]);

  const updateParams = useCallback(
    (patch: Record<string, string | null>) => {
      const next = new URLSearchParams(params);
      Object.entries(patch).forEach(([key, value]) => {
        if (value) next.set(key, value);
        else next.delete(key);
      });
      setParams(next, { replace: true });
    },
    [params, setParams]
  );

  const loadObjects = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const data = await fetchKnowledgeObjects({
        q: query || undefined,
        type: type || undefined,
        domain: domain || undefined,
        status: status || undefined,
        limit: 80,
      });
      setObjects(data.items);
      setTotal(data.total);
      const domainSet = new Set(data.items.map((item) => item.domain).filter(Boolean));
      setDomains((prev) => Array.from(new Set([...prev, ...domainSet])) as string[]);
    } catch (err) {
      setObjects([]);
      setTotal(0);
      setError(
        err instanceof Error ? err.message : "No pudimos cargar los objetos de conocimiento."
      );
    } finally {
      setLoading(false);
    }
  }, [query, type, domain, status]);

  const loadGraph = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const data = await fetchKnowledgeGraph({
        focus_id: focusId || undefined,
        types: type || undefined,
        domains: domain || undefined,
        limit_nodes: 120,
        limit_edges: 300,
      });
      setGraph(data);
    } catch (err) {
      setGraph(null);
      setError(err instanceof Error ? err.message : "No pudimos cargar el grafo.");
    } finally {
      setLoading(false);
    }
  }, [focusId, type, domain]);

  useEffect(() => {
    if (view === "graph") void loadGraph();
    else void loadObjects();
  }, [view, loadGraph, loadObjects]);

  useEffect(() => {
    setSearchDraft(query);
  }, [query]);

  const openDetail = useCallback(async (id: string) => {
    setDetailError("");
    setVerifyState("");
    setDetail(null);
    try {
      const data = await fetchKnowledgeObject(id);
      setDetail(data);
    } catch (err) {
      setDetailError(
        err instanceof Error ? err.message : "No pudimos abrir el objeto."
      );
    }
  }, []);

  const onVerify = async () => {
    if (!detail) return;
    setVerifyState("saving");
    try {
      const updated = await verifyKnowledgeObject(detail.object.id);
      setDetail({ ...detail, object: { ...detail.object, ...updated } });
      setVerifyState("ok");
    } catch (err) {
      setVerifyState(
        err instanceof Error
          ? `No se pudo verificar: ${err.message}`
          : "No se pudo verificar (permiso knowledge:validate requerido)."
      );
    }
  };

  const submitSearch = (event: React.FormEvent) => {
    event.preventDefault();
    updateParams({ q: searchDraft.trim() || null });
  };

  const drawerOpen = Boolean(detail || detailError);

  return (
    <KnowledgeLayout>
      <PageHeader
        title={KNOWLEDGE_HEADINGS.model}
        subtitle="Explora el modelo de negocio: conceptos, entidades, relaciones, reglas y métricas con su evidencia."
        actions={
          <div className="flex gap-1" role="tablist" aria-label="Vistas del modelo">
            {VIEW_TABS.map((tab) => (
              <button
                key={tab.id}
                type="button"
                role="tab"
                aria-selected={view === tab.id}
                className={cn(
                  "btn btn-secondary min-h-9 px-3 text-xs",
                  view === tab.id && "border-accent text-text"
                )}
                onClick={() => updateParams({ view: tab.id === "explorer" ? null : tab.id })}
              >
                <tab.icon size={14} aria-hidden />
                {tab.label}
              </button>
            ))}
          </div>
        }
      />

      <div className="flex flex-col gap-4">
        <Panel flat className="p-3">
          <form className="flex flex-col gap-2 sm:flex-row sm:items-center" onSubmit={submitSearch}>
            <label className="sr-only" htmlFor="model-search">
              Buscar en el modelo
            </label>
            <input
              id="model-search"
              className="input"
              placeholder="Buscar concepto, entidad, regla, métrica…"
              value={searchDraft}
              onChange={(e) => setSearchDraft(e.target.value)}
            />
            <Button type="submit" variant="secondary" leadingIcon={MagnifyingGlass}>
              Buscar
            </Button>
            <Select
              aria-label="Tipo"
              value={type}
              onChange={(e) => updateParams({ type: e.target.value || null })}
              className="sm:w-[180px]"
            >
              {TYPE_FILTERS.map((option) => (
                <option key={option.value} value={option.value}>
                  {option.label}
                </option>
              ))}
            </Select>
            <Select
              aria-label="Estado"
              value={status}
              onChange={(e) => updateParams({ status: e.target.value || null })}
              className="sm:w-[160px]"
            >
              <option value="">Todos los estados</option>
              <option value="discovered">Descubierto</option>
              <option value="inferred">Inferido</option>
              <option value="verified">Verificado</option>
              <option value="deprecated">Deprecado</option>
            </Select>
            <Select
              aria-label="Dominio"
              value={domain}
              onChange={(e) => updateParams({ domain: e.target.value || null })}
              className="sm:w-[170px]"
            >
              <option value="">Todos los dominios</option>
              {domains.map((item) => (
                <option key={item} value={item}>
                  {item}
                </option>
              ))}
            </Select>
          </form>
          {(query || type || domain || status || focusId) && (
            <div className="mt-2 flex flex-wrap items-center gap-2 text-xs text-muted">
              {query && <span>Búsqueda: «{query}»</span>}
              {focusId && <span>Enfocado en un nodo</span>}
              <button
                type="button"
                className="underline underline-offset-2"
                onClick={() =>
                  updateParams({ q: null, type: null, domain: null, status: null, focus: null })
                }
              >
                Limpiar filtros
              </button>
            </div>
          )}
        </Panel>

        <ErrorInline message={error} className="mb-0" />

        {loading && (
          <div className="flex flex-col gap-3" aria-busy="true">
            <Skeleton className="h-[92px] rounded-lg" />
            <Skeleton className="h-[92px] rounded-lg" />
            <Skeleton className="h-[92px] rounded-lg" />
          </div>
        )}

        {!loading && view === "graph" && (
          <Panel className="p-4">
            <GraphView
              payload={graph}
              selectedId={detail?.object.id ?? focusId}
              onSelect={(id) => void openDetail(id)}
              onExpand={(id) => updateParams({ focus: id })}
            />
          </Panel>
        )}

        {!loading && view !== "graph" && objects.length === 0 && !error && (
          <Panel>
            <EmptyState
              icon={Brain}
              title="Sin objetos que coincidan"
              body="Prueba con otro término o limpia los filtros. Si el modelo está vacío, ejecuta aprendizaje sobre una fuente."
            />
          </Panel>
        )}

        {!loading && view === "explorer" && objects.length > 0 && (
          <div className="grid grid-cols-1 gap-3 xl:grid-cols-2">
            {objects.map((item) => (
              <button
                key={item.id}
                type="button"
                onClick={() => void openDetail(item.id)}
                className="panel panel-body text-left transition-colors hover:border-accent"
              >
                <div className="flex items-start justify-between gap-3">
                  <div className="min-w-0">
                    <p className="truncate text-sm font-medium text-text">{item.name}</p>
                    <p className="mt-1 line-clamp-2 text-xs text-muted">
                      {item.description || "Sin descripción de negocio."}
                    </p>
                  </div>
                  {item.evidence_count > 0 && (
                    <span className="shrink-0 text-xs text-muted">
                      {item.evidence_count} evid.
                    </span>
                  )}
                </div>
                <div className="mt-3">
                  <ObjectMeta item={item} />
                </div>
              </button>
            ))}
          </div>
        )}

        {!loading && view === "table" && objects.length > 0 && (
          <Panel className="overflow-hidden">
            <div className="overflow-x-auto">
              <table className="w-full text-left text-sm">
                <thead className="border-b border-border text-xs text-muted">
                  <tr>
                    <th className="px-4 py-2.5 font-medium">Nombre</th>
                    <th className="px-4 py-2.5 font-medium">Tipo</th>
                    <th className="px-4 py-2.5 font-medium">Dominio</th>
                    <th className="px-4 py-2.5 font-medium">Estado</th>
                    <th className="px-4 py-2.5 font-medium">Confianza</th>
                    <th className="px-4 py-2.5 font-medium">Evidencia</th>
                    <th className="px-4 py-2.5 font-medium">Actualizado</th>
                  </tr>
                </thead>
                <tbody>
                  {objects.map((item) => (
                    <tr
                      key={item.id}
                      className="cursor-pointer border-b border-border last:border-0 hover:bg-soft/60"
                      onClick={() => void openDetail(item.id)}
                    >
                      <td className="max-w-[280px] truncate px-4 py-2.5 text-text">{item.name}</td>
                      <td className="px-4 py-2.5 text-muted">{objectTypeLabel(item.type)}</td>
                      <td className="px-4 py-2.5 text-muted">{item.domain || "—"}</td>
                      <td className="px-4 py-2.5">
                        <span className={cn("badge", statusTone(item.status))}>{item.status}</span>
                      </td>
                      <td className="px-4 py-2.5 text-muted">
                        {item.confidence != null ? `${Math.round(item.confidence * 100)}%` : "—"}
                      </td>
                      <td className="px-4 py-2.5 text-muted">{item.evidence_count}</td>
                      <td className="px-4 py-2.5 text-muted">
                        {item.updated_at ? fmtDateTime(item.updated_at) : "—"}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </Panel>
        )}

        {!loading && view !== "graph" && objects.length > 0 && (
          <p className="text-xs text-muted">
            {fmtNum(objects.length)} de {fmtNum(total)} objetos.
          </p>
        )}
      </div>

      <Drawer
        open={drawerOpen}
        onOpenChange={(open) => {
          if (!open) {
            setDetail(null);
            setDetailError("");
          }
        }}
        title={detail?.object.display_name || detail?.object.name || "Objeto de conocimiento"}
        description={detail ? objectTypeLabel(detail.object.type) : undefined}
        width={560}
      >
        {detailError && <ErrorInline message={detailError} className="mx-5 my-4" />}
        {!detail && !detailError && <p className="px-5 py-4 text-sm text-muted">Cargando…</p>}
        {detail && (
          <div className="flex flex-col">
            <div className="flex flex-wrap items-center gap-2 px-5 py-4">
              <ObjectMeta item={detail.object} />
              {detail.object.source_of_truth && (
                <span className="text-xs text-muted">
                  Fuente: {detail.object.source_of_truth}
                </span>
              )}
            </div>
            {detail.object.description && (
              <p className="px-5 pb-4 text-sm text-muted">{detail.object.description}</p>
            )}
            {verifyState && (
              <p
                className={cn(
                  "px-5 pb-3 text-xs",
                  verifyState === "ok" ? "text-ok" : "text-danger"
                )}
              >
                {verifyState === "ok" ? "Objeto verificado." : verifyState}
              </p>
            )}
            <DetailSection title="Relaciones" count={detail.edges.length} empty="Sin relaciones.">
              <ul className="flex flex-col gap-2">
                {detail.edges.map((edge) => (
                  <li key={edge.id} className="text-sm">
                    <span className="text-text">
                      {edge.direction === "in" ? "← " : ""}
                      {edge.direction === "in" ? edge.subject_name : edge.object_name}
                    </span>
                    <span className="mx-1 text-muted">—{edge.predicate}→</span>
                    <span className="text-text">
                      {edge.direction === "in" ? edge.object_name : edge.subject_name}
                    </span>
                    <span className="ml-2 text-xs text-muted">
                      {edge.relationship_type} · {Math.round(edge.confidence * 100)}% ·{" "}
                      {edge.status}
                    </span>
                  </li>
                ))}
              </ul>
            </DetailSection>
            <DetailSection
              title="Afirmaciones"
              count={detail.assertions.length}
              empty="Sin afirmaciones registradas."
            >
              <ul className="flex flex-col gap-3">
                {detail.assertions.map((assertion) => (
                  <li key={assertion.id} className="text-sm">
                    <p className="text-text">
                      {assertion.subject_label} <span className="text-muted">{assertion.predicate}</span>{" "}
                      {assertion.object_value}
                    </p>
                    <p className="mt-0.5 flex flex-wrap items-center gap-1.5 text-xs text-muted">
                      <span className={cn("badge", statusTone(assertion.status))}>
                        {assertion.status}
                      </span>
                      <span>{Math.round(assertion.confidence * 100)}%</span>
                      <span>{assertion.method}</span>
                      <span>{assertion.evidence_count} evid.</span>
                    </p>
                  </li>
                ))}
              </ul>
            </DetailSection>
            <DetailSection
              title="Evidencia"
              count={detail.evidence.length}
              empty="Sin evidencia adjunta."
            >
              <ul className="flex flex-col gap-3">
                {detail.evidence.map((evidence) => (
                  <li key={evidence.id} className="rounded-md border border-border p-3 text-xs">
                    <p className="text-sm text-text">{evidence.excerpt}</p>
                    <p className="mt-1 text-muted">
                      {evidence.locator || evidence.table_reference || "—"} ·{" "}
                      {evidence.evidence_type}
                      {evidence.strength != null
                        ? ` · fuerza ${Math.round(evidence.strength * 100)}%`
                        : ""}
                      {evidence.page ? ` · página ${evidence.page}` : ""}
                    </p>
                  </li>
                ))}
              </ul>
            </DetailSection>
            <DetailSection
              title="Usado por / impacto"
              count={detail.impact.count}
              empty="Nada depende de este objeto todavía."
            >
              <ul className="flex flex-col gap-1.5 text-sm">
                {detail.impact.dependents.map((dependent) => (
                  <li key={`${dependent.kind}-${dependent.id}`} className="text-text">
                    {dependent.name}
                    <span className="ml-2 text-xs text-muted">
                      {dependent.kind}
                      {dependent.via ? ` · ${dependent.via}` : ""}
                    </span>
                  </li>
                ))}
              </ul>
            </DetailSection>
            <DetailSection
              title="Historial"
              count={detail.versions.length}
              empty="Sin cambios registrados."
            >
              <ul className="flex flex-col gap-1.5 text-xs text-muted">
                {detail.versions.map((version) => (
                  <li key={version.version}>
                    v{version.version} · {version.change_kind} ·{" "}
                    {version.created_at ? fmtDateTime(version.created_at) : "—"}
                  </li>
                ))}
              </ul>
            </DetailSection>
            <DetailSection
              title="Preguntas abiertas"
              count={detail.questions.length}
              empty="Sin preguntas abiertas."
            >
              <ul className="flex flex-col gap-1.5 text-sm">
                {detail.questions.map((question) => (
                  <li key={question.id} className="text-text">
                    {question.title}
                    <span className="ml-2 text-xs text-muted">{question.priority}</span>
                  </li>
                ))}
              </ul>
            </DetailSection>
          </div>
        )}
        <div className="flex items-center justify-between gap-2 border-t border-border px-5 py-3">
          <Button
            variant="primary"
            disabled={!detail || detail.object.status === "verified" || verifyState === "saving"}
            onClick={() => void onVerify()}
          >
            Verificar
          </Button>
          {detail && (
            <Button
              variant="ghost"
              leadingIcon={ArrowsOut}
              onClick={() => updateParams({ focus: detail.object.id, view: "graph" })}
            >
              Ver en el grafo
            </Button>
          )}
          <Button
            variant="ghost"
            leadingIcon={X}
            onClick={() => {
              setDetail(null);
              setDetailError("");
            }}
          >
            Cerrar
          </Button>
        </div>
      </Drawer>
    </KnowledgeLayout>
  );
}
