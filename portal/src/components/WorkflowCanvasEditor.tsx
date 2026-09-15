import { ChartLineUp, Plus, WarningOctagon, X } from "@phosphor-icons/react";
import { useCallback, useEffect, useMemo, useState } from "react";
import { api } from "../api";
import { useAuth } from "../auth";
import type { NodeBusinessSchema, NodeSchemasPayload, ParameterLevel } from "../lib/businessSchema";
import type { DataCatalogPayload, NodeSamples } from "../lib/dataPicker";
import type { MarketRec, ShopInstall } from "../lib/marketplaceCanvas";
import type { GraphNode, NodeMeta, WorkflowGraph } from "../lib/workflowGraph";
import { makeNode, newEdgeId, prepareGraphForSave, triggerConfigOf, triggerTypeOf } from "../lib/workflowGraph";
import { fetchNodeCatalog, libraryWithCatalog, catalogCategoryLabels } from "../lib/workflowCatalog";
import { NodeConfigPanel } from "./NodeConfigPanel";
import { NodeLibrary, type MarketplaceContext, type MxRecommendation } from "./NodeLibrary";
import { WorkflowCanvas, type RunOverlay } from "./WorkflowCanvas";
import type { RunDetail } from "./WorkflowRunInspector";
import { ErrorInline } from "./ui";

type Props = {
  workflowId: string | null;
  graph: WorkflowGraph | null;
  onChangeGraph: (g: WorkflowGraph, triggerType: "webhook" | "schedule" | "event", triggerConfig: Record<string, unknown>) => void;
  kbs: { id: string; name: string }[];
  agents: { id: string; name: string }[];
  /** Resultado del último run: pinta estados y respuestas sobre el grafo. */
  overlay?: RunOverlay;
  /** Selección controlada: el dock de prueba también selecciona nodos. */
  selectedNodeId: string | null;
  onSelectNode: (id: string | null) => void;
  /** Nivel de configuración (Simple/Guided/Advanced), compartido con el estudio. */
  configLevel?: ParameterLevel;
  onConfigLevelChange?: (level: ParameterLevel) => void;
  /** Último run: alimenta las pestañas Input/Output/Run del inspector. */
  run?: RunDetail | null;
  pinnedNodes?: string[];
  onPinData?: (nodeId: string, output: Record<string, unknown>) => void;
  onUnpinData?: (nodeId: string) => void;
  onRunPartial?: (nodeId: string, mode: "node" | "until_node" | "from_node") => void;
  partialBusy?: string;
  /** Alto del lienzo y del rail (el estudio lo pone a viewport). */
  heightClass?: string;
};

/** Nodos que solo sirven de marco: no cuentan como "el usuario ya armó algo". */
function isScaffold(n: GraphNode): boolean {
  return n.type === "end" || n.type.startsWith("trigger_");
}

export function WorkflowCanvasEditor({
  workflowId,
  graph,
  onChangeGraph,
  kbs,
  agents,
  overlay,
  selectedNodeId,
  onSelectNode,
  configLevel,
  onConfigLevelChange,
  run,
  pinnedNodes,
  onPinData,
  onUnpinData,
  onRunPartial,
  partialBusy,
  heightClass = "h-[560px]",
}: Props) {
  const { session } = useAuth();
  const [selectedEdge, setSelectedEdge] = useState<string | null>(null);
  const [error, setError] = useState("");
  const [nodeSchemas, setNodeSchemas] = useState<Record<string, NodeBusinessSchema> | null>(null);
  const [catalogNodes, setCatalogNodes] = useState<Record<string, NodeMeta> | null>(null);
  const [categoryLabels, setCategoryLabels] = useState<Record<string, string> | null>(null);
  const [samples, setSamples] = useState<NodeSamples | null>(null);
  const [dataCatalog, setDataCatalog] = useState<DataCatalogPayload | null>(null);
  const [mxInstalls, setMxInstalls] = useState<{ id: string; integration: { slug: string; name: string } }[]>([]);
  const [mxActions, setMxActions] = useState<Record<string, { action_id: string; display_name: string }[]>>({});
  const [mkt, setMkt] = useState<MarketplaceContext | null>(null);
  const [shop, setShop] = useState<ShopInstall | null>(null);
  const [shopBusy, setShopBusy] = useState(false);
  const [shopPurpose, setShopPurpose] = useState("");
  const [cost, setCost] = useState<{
    per_run: number;
    monthly: number;
    calls_per_run: number;
    bulk_warning: boolean;
    currency: string;
    ai_calls_per_run?: number;
    knowledge_calls_per_run?: number;
    cognitive_calls_per_run?: number;
    warnings?: { code: string; message: string }[];
  } | null>(null);
  const [emptyDismissed, setEmptyDismissed] = useState(false);

  useEffect(() => {
    if (!session) return;
    api<{ installs: { id: string; integration: { slug: string; name: string } }[] }>(
      "/api/v1/integrations/installs",
      { token: session.token, organizationId: session.organizationId }
    )
      .then((d) => setMxInstalls(d.installs || []))
      .catch(() => undefined);

    api<MarketplaceContext>("/api/v1/workflows/marketplace/context", {
      token: session.token,
      organizationId: session.organizationId,
    })
      .then((d) => setMkt(d))
      .catch(() => undefined);

    api<NodeSchemasPayload>("/api/v1/workflows/node-schemas", {
      token: session.token,
      organizationId: session.organizationId,
    })
      .then((d) => {
        const map: Record<string, NodeBusinessSchema> = {};
        for (const schema of d.schemas ?? []) map[schema.node_type] = schema;
        setNodeSchemas(map);
      })
      .catch(() => undefined);
  }, [session, workflowId]);

  // Catálogo semántico backend: nodos autorizados/disponibles del tenant.
  // Si el endpoint falla, el rail usa NODE_LIBRARY local (fallback).
  useEffect(() => {
    if (!session) return;
    let alive = true;
    void fetchNodeCatalog(
      <T,>(path: string) =>
        api<T>(path, { token: session.token, organizationId: session.organizationId }),
      session.organizationId,
    ).then((payload) => {
      if (alive) {
        setCatalogNodes(payload ? libraryWithCatalog(payload) : null);
        setCategoryLabels(payload ? catalogCategoryLabels(payload) : null);
      }
    });
    return () => {
      alive = false;
    };
  }, [session, workflowId]);

  // Live Preview / Data Picker: outputs reales del último run (se refresca
  // cuando el estudio pinta un nuevo overlay).
  useEffect(() => {
    if (!session || !workflowId) {
      setSamples(null);
      return;
    }
    let alive = true;
    api<NodeSamples>(`/api/v1/workflows/${workflowId}/sample-outputs`, {
      token: session.token,
      organizationId: session.organizationId,
    })
      .then((d) => {
        if (alive) setSamples(d);
      })
      .catch(() => {
        if (alive) setSamples(null);
      });
    return () => {
      alive = false;
    };
  }, [session, workflowId, overlay]);

  // Data Catalog backend (Fase 6): refs tipadas + etiquetas de negocio.
  // Si falla, el Data Picker usa el cálculo local (contratos + samples).
  useEffect(() => {
    if (!session || !workflowId) {
      setDataCatalog(null);
      return;
    }
    let alive = true;
    api<DataCatalogPayload>(`/api/v1/workflows/${workflowId}/data-catalog`, {
      token: session.token,
      organizationId: session.organizationId,
    })
      .then((d) => {
        if (alive) setDataCatalog(d);
      })
      .catch(() => {
        if (alive) setDataCatalog(null);
      });
    return () => {
      alive = false;
    };
  }, [session, workflowId, overlay]);

  // Recomendaciones y costo según el grafo actual (debounce ligero).
  useEffect(() => {
    if (!session || !graph || graph.nodes.length <= 1) {
      setCost(null);
      return;
    }
    const id = window.setTimeout(() => {
      const g = prepareGraphForSave(graph);
      void api<{ recommendations: MxRecommendation[] }>("/api/v1/workflows/marketplace/recommend", {
        method: "POST",
        token: session.token,
        organizationId: session.organizationId,
        body: JSON.stringify({ graph: g }),
      })
        .then((d) => setMkt((prev) => (prev ? { ...prev, recommendations: d.recommendations || [] } : prev)))
        .catch(() => undefined);
      void api<{
        per_run: number;
        monthly: number;
        calls_per_run: number;
        bulk_warning: boolean;
        currency: string;
        ai_calls_per_run?: number;
        knowledge_calls_per_run?: number;
        cognitive_calls_per_run?: number;
        warnings?: { code: string; message: string }[];
      }>(
        "/api/v1/workflows/cost-estimate",
        {
          method: "POST",
          token: session.token,
          organizationId: session.organizationId,
          body: JSON.stringify({ graph: g, trigger_config: triggerConfigOf(g) }),
        }
      )
        .then(setCost)
        .catch(() => undefined);
    }, 600);
    return () => window.clearTimeout(id);

  }, [session, graph]);

  const ensureActions = useCallback(
    async (installId: string) => {
      if (!session || !installId || mxActions[installId]) return;
      const install = mxInstalls.find((i) => i.id === installId);
      if (!install) return;
      try {
        const m = await api<{ capabilities: { actions: { action_id: string; display_name: string }[] }[] }>(
          `/api/v1/integrations/catalog/${install.integration.slug}`,
          { token: session.token, organizationId: session.organizationId }
        );
        const actions = (m.capabilities ?? []).flatMap((c) => c.actions ?? []);
        setMxActions((prev) => ({ ...prev, [installId]: actions }));
      } catch {
        setMxActions((prev) => ({ ...prev, [installId]: [] }));
      }
    },

    [session, mxInstalls, mxActions]
  );

  useEffect(() => {
    if (selectedNodeId && graph) {
      const n = graph.nodes.find((x) => x.id === selectedNodeId);
      if (n?.type === "marketplace_action" && n.config.install_id) {
        void ensureActions(String(n.config.install_id));
      }
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedNodeId, graph]);

  useEffect(() => {
    setSelectedEdge(null);
  }, [workflowId]);

  const local = graph;

  /**
   * Añade un nodo y lo conecta solo: desde el nodo seleccionado (o el trigger).
   * Si el origen ya apuntaba a otro nodo, el nuevo se intercala en medio para
   * que nunca quede huérfano.
   */
  function insertNode(nodeType: string, config?: Record<string, unknown>) {
    if (!graph) return;
    const source =
      graph.nodes.find((n) => n.id === selectedNodeId && n.output_ports.length > 0) ??
      graph.nodes.find((n) => n.type.startsWith("trigger_")) ??
      null;

    const spawn = source
      ? { x: source.position.x + 300, y: source.position.y + 20 }
      : { x: 60, y: 80 };
    while (graph.nodes.some((n) => Math.abs(n.position.x - spawn.x) < 40 && Math.abs(n.position.y - spawn.y) < 40)) {
      spawn.y += 150;
    }

    const n = makeNode(nodeType, spawn);
    if (config) n.config = { ...n.config, ...config };

    let edges = graph.edges.map((e) => ({ ...e }));
    if (source && n.input_ports.length > 0) {
      const port = source.output_ports[0]?.name ?? "out";
      const outPort = n.output_ports[0]?.name;
      // Intercalar: origen → nuevo → lo que seguía (si el nuevo tiene salida).
      edges = edges.map((e) =>
        e.from_node === source.id && e.from_port === port && outPort
          ? { ...e, from_node: n.id, from_port: outPort }
          : e
      );
      edges.push({ id: newEdgeId(), from_node: source.id, from_port: port, to_node: n.id, to_port: n.input_ports[0].name });
    }

    const copy: WorkflowGraph = {
      ...graph,
      nodes: [...graph.nodes.map((x) => ({ ...x, config: { ...x.config } })), n],
      edges,
      entrypoints: graph.entrypoints.length ? graph.entrypoints : [n.id],
    };
    onChangeGraph(copy, triggerTypeOf(copy), triggerConfigOf(copy));
    onSelectNode(n.id);
    setSelectedEdge(null);
  }

  function addMarketplaceAction(installId: string, action: { action_id: string; display_name: string; renderer?: string | null }) {
    insertNode("marketplace_action", {
      install_id: installId,
      action_id: action.action_id,
      renderer: action.renderer ?? null,
      inputs: {},
    });
  }

  async function addRecommendation(rec: MxRecommendation) {
    // Instala si falta; luego añade el nodo con la acción recomendada.
    if (!session) return;
    const available = mkt?.available.find((a) => a.slug === rec.integration_slug);
    const want = available?.actions.find((a) => a.action_id === rec.action_id);
    if (want && available) {
      const installed = mkt?.installed.find((i) => i.integration.slug === rec.integration_slug);
      if (!installed) {
        setShop({
          slug: available.slug,
          name: available.name,
          description: available.description ?? "",
          requires_credentials: Boolean(available.requires_credentials),
          requires_purpose: Boolean(available.requires_purpose),
          actions: [want],
        });
        return;
      }
      addMarketplaceAction(installed.install_id, want);
      return;
    }
    insertNode("marketplace_action", { install_id: "", action_id: rec.action_id, inputs: {} });
  }

  async function installFromDrawer(slug: string) {
    if (!session) return;
    setShopBusy(true);
    setError("");
    try {
      const r = await api<MarketRec>(`/api/v1/workflows/marketplace/install`, {
        method: "POST",
        token: session.token,
        organizationId: session.organizationId,
        body: JSON.stringify({ integration_slug: slug, purpose: shopPurpose.trim() || null }),
      });
      const fresh = await api<MarketplaceContext>("/api/v1/workflows/marketplace/context", {
        token: session.token,
        organizationId: session.organizationId,
      });
      setMkt(fresh);
      setError(`Integración instalada ✓ — ${r.integration.name} ya está en el canvas.`);
      setShop(null);
      setShopPurpose("");
    } catch (e) {
      setError(e instanceof Error ? e.message : "Error");
    } finally {
      setShopBusy(false);
    }
  }

  function patch(updater: (g: WorkflowGraph) => WorkflowGraph) {
    if (!graph) return;
    const copy = updater(structuredClone(graph));
    onChangeGraph(copy, triggerTypeOf(copy), triggerConfigOf(copy));
  }

  const deleteNode = useCallback(
    (id: string) => {
      patch((g) => ({
        ...g,
        nodes: g.nodes.filter((n) => n.id !== id),
        edges: g.edges.filter((e) => e.from_node !== id && e.to_node !== id),
        entrypoints: g.entrypoints.filter((e) => e !== id),
      }));
      onSelectNode(null);
    },
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [graph]
  );

  const deleteEdge = useCallback(
    (id: string) => {
      patch((g) => ({ ...g, edges: g.edges.filter((e) => e.id !== id) }));
      setSelectedEdge(null);
    },
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [graph]
  );

  // El grafo de arranque ya trae trigger + fin: el hint aparece mientras no
  // haya ningún nodo con lógica propia.
  const isEmptyCanvas = !!local && local.nodes.every(isScaffold) && !emptyDismissed;

  function addSuggestion(kind: "verify" | "sales" | "invoice" | "inventory" | "agent") {
    if (!graph) return;
    const nodes: GraphNode[] = [];
    const edges: WorkflowGraph["edges"] = [];
    const trigger =
      graph.nodes.find((n) => n.type.startsWith("trigger_")) ?? makeNode("trigger_webhook", { x: 40, y: 60 });
    let prev = trigger.id;

    if (kind === "agent") {
      const ask = makeNode("llm", { x: 360, y: 80 });
      const first = agents[0];
      ask.config = {
        ...ask.config,
        prompt: "{{trigger.message}}",
        agent_id: first?.id ?? "",
        agent_name: first?.name ?? "",
      };
      nodes.push(ask);
      edges.push({ id: newEdgeId(), from_node: prev, from_port: "out", to_node: ask.id, to_port: "in" });
      prev = ask.id;
    } else if (kind === "verify") {
      const act = makeNode("marketplace_action", { x: 360, y: 80 });
      const install = mxInstalls[0];
      const action = install ? (mxActions[install.id] ?? [])[0] : undefined;
      if (install && action) {
        act.config = { install_id: install.id, action_id: action.action_id, inputs: { ruc: "{{trigger.ruc}}" } };
      }
      nodes.push(act);
      edges.push({ id: newEdgeId(), from_node: prev, from_port: "out", to_node: act.id, to_port: "in" });
      const cond = makeNode("condition", { x: 680, y: 120 });
      cond.config = { field: `{{nodes.${act.id}.output.status}}`, operator: "!=", value: "ACTIVO" };
      nodes.push(cond);
      edges.push({ id: newEdgeId(), from_node: act.id, from_port: "out", to_node: cond.id, to_port: "in" });
      prev = cond.id;
    } else {
      const q = makeNode("query_business_data", { x: 360, y: 80 });
      q.config = { ask: kind === "sales" ? "Ventas de ayer" : kind === "invoice" ? "Facturas por verificar" : "Stock bajo" };
      nodes.push(q);
      edges.push({ id: newEdgeId(), from_node: prev, from_port: "out", to_node: q.id, to_port: "in" });
      prev = q.id;
    }

    const notify = makeNode("notify", { x: 1000, y: 140 });
    notify.config = {
      channel: "in_app",
      title: kind === "verify" ? "Cliente no activo" : kind === "agent" ? "Respuesta del agente" : "Reporte",
      message: `{{nodes.${prev}.output}}`,
    };
    nodes.push(notify);
    edges.push({ id: newEdgeId(), from_node: prev, from_port: "out", to_node: notify.id, to_port: "in" });

    const keep = graph.nodes.filter((n) => n.type.startsWith("trigger_"));
    const copy: WorkflowGraph = {
      ...graph,
      nodes: [...(keep.length ? keep : [trigger]).map((x) => ({ ...x, config: { ...x.config } })), ...nodes],
      edges,
      entrypoints: (keep.length ? keep : [trigger]).map((x) => x.id),
    };
    onChangeGraph(copy, triggerTypeOf(copy), triggerConfigOf(copy));
    onSelectNode(nodes[0].id);
  }

  const selectedNodeObj = local?.nodes.find((n) => n.id === selectedNodeId) ?? null;
  const selectedEdgeObj = local?.edges.find((e) => e.id === selectedEdge) ?? null;
  const inspectorOpen = Boolean(selectedNodeObj || selectedEdgeObj);

  const suggestions = useMemo(
    () =>
      [
        ["agent", "Preguntar a un agente"],
        ["sales", "Reporte diario de ventas"],
        ["invoice", "Verificar facturas"],
        ["inventory", "Alerta de inventario"],
        ["verify", "Verificar clientes nuevos"],
      ] as const,
    []
  );

  return (
    <div className={`flex min-h-0 gap-3 ${heightClass}`} data-testid="workflow-canvas-editor">
      <NodeLibrary
        className="h-full"
        usedTypes={local ? local.nodes.map((n) => n.type) : []}
        nodes={catalogNodes}
        categoryLabels={categoryLabels}
        onAdd={(meta) => insertNode(meta.type)}
        marketplace={mkt}
        onAddMarketplaceAction={addMarketplaceAction}
        onAddRecommendation={(r) => void addRecommendation(r)}
        onInstall={(slug) => {
          const a = mkt?.available.find((x) => x.slug === slug);
          if (a) {
            setShop({ slug: a.slug, name: a.name, description: a.description ?? "", requires_credentials: a.requires_credentials, requires_purpose: a.requires_purpose, actions: a.actions });
          }
        }}
      />

      <div className="relative min-w-0 flex-1">
        {local ? (
          <WorkflowCanvas
            className="h-full"
            graph={local}
            agents={agents}
            onChange={(g) => onChangeGraph(g, triggerTypeOf(g), triggerConfigOf(g))}
            selectedNodeId={selectedNodeId}
            onSelectNode={onSelectNode}
            selectedEdgeId={selectedEdge}
            onSelectEdge={setSelectedEdge}
            overlay={overlay}
            rightInset={inspectorOpen ? 320 : 0}
          />
        ) : (
          <div className="flex h-full w-full items-center justify-center rounded-lg border border-dashed border-border bg-soft/30 text-xs text-faint">
            {workflowId ? "Cargando grafo…" : "Guarda el workflow para empezar a editar su canvas."}
          </div>
        )}

        {error && (
          <div className="absolute top-3 left-1/2 z-30 w-[min(420px,90%)] -translate-x-1/2">
            <ErrorInline>{error}</ErrorInline>
          </div>
        )}

        {isEmptyCanvas && (
          <div
            className="absolute bottom-4 left-4 z-20 w-[min(340px,calc(100%-2rem))] rounded-lg border border-accent/30 bg-surface/95 p-3 shadow-panel backdrop-blur-sm"
            data-testid="wf-empty-hint"
          >
            <p className="text-sm font-medium text-text">¿Qué quieres automatizar?</p>
            <p className="mt-0.5 text-[11px] text-muted">
              Arranca con una plantilla; queda en el lienzo y la editas ahí mismo.
            </p>
            <div className="mt-2 flex flex-wrap gap-1.5">
              {suggestions.map(([kind, label]) => (
                <button
                  key={kind}
                  type="button"
                  className="btn btn-secondary min-h-8 px-2 text-[11px]"
                  data-testid={`wf-suggest-${kind}`}
                  onClick={() => addSuggestion(kind)}
                >
                  {label}
                </button>
              ))}
              <button
                type="button"
                className="btn btn-ghost min-h-8 px-2 text-[11px] text-faint"
                data-testid="wf-suggest-blank"
                onClick={() => setEmptyDismissed(true)}
              >
                Empezar vacío
              </button>
            </div>
          </div>
        )}

        {cost && cost.calls_per_run > 0 && !isEmptyCanvas && (
          <div className="absolute bottom-3 left-3 z-20 flex flex-wrap items-center gap-2">
            <span
              className="inline-flex items-center gap-1 rounded-md border border-border bg-surface/95 px-2 py-1 text-[10px] text-muted"
              data-testid="wf-cost"
              title={`${cost.calls_per_run} llamadas por run`}
            >
              <ChartLineUp size={12} aria-hidden />~ S/ {cost.per_run.toFixed(2)} / run · S/ {cost.monthly.toFixed(2)} / mes
            </span>
            {cost.bulk_warning && (
              <span
                className="inline-flex items-center gap-1 rounded-md border border-danger/40 bg-danger-soft px-2 py-1 text-[10px] text-danger"
                data-testid="wf-bulk-warning"
              >
                <WarningOctagon size={12} aria-hidden />
                {cost.calls_per_run} llamadas pagadas por run
              </span>
            )}
            {(cost.warnings ?? []).slice(0, 2).map((warning) => (
              <span
                key={warning.code}
                className="inline-flex items-center gap-1 rounded-md border border-warn/40 bg-warn-soft px-2 py-1 text-[10px] text-warn"
                data-testid={`wf-cost-warning-${warning.code}`}
                title={warning.message}
              >
                <WarningOctagon size={12} aria-hidden />
                {warning.message}
              </span>
            ))}
          </div>
        )}

        {inspectorOpen && local && (
          <div className="absolute top-3 right-3 bottom-3 z-30 flex w-[19rem] max-w-[calc(100%-1.5rem)]">
            <NodeConfigPanel
              className="w-full"
              graph={local}
              node={selectedNodeObj}
              edge={selectedEdgeObj}
              onChange={(g) => onChangeGraph(g, triggerTypeOf(g), triggerConfigOf(g))}
              onDeleteNode={deleteNode}
              onDeleteEdge={deleteEdge}
              onClose={() => {
                onSelectNode(null);
                setSelectedEdge(null);
              }}
              kbs={kbs}
              agents={agents}
              mxInstalls={mxInstalls}
              mxActions={mxActions}
              nodeSchemas={nodeSchemas}
              catalogNodes={catalogNodes}
              dataCatalog={dataCatalog}
              samples={samples}
              run={run}
              pinned={Boolean(selectedNodeObj && pinnedNodes?.includes(selectedNodeObj.id))}
              onPinData={onPinData}
              onUnpinData={onUnpinData}
              onRunPartial={onRunPartial}
              partialBusy={partialBusy}
              configLevel={configLevel}
              onConfigLevelChange={onConfigLevelChange}
            />
          </div>
        )}
      </div>

      {shop && (
        <div className="fixed inset-0 z-40 flex items-end justify-center bg-black/40 p-0 sm:items-center sm:p-6" data-testid="wf-mkt-drawer">
          <div className="max-h-[90dvh] w-full max-w-md overflow-y-auto rounded-t-lg border border-border bg-surface p-5 sm:rounded-lg">
            <div className="flex items-start justify-between gap-3">
              <div className="flex items-center gap-2">
                <MarketBadge slug={shop.slug} />
                <div>
                  <p className="text-sm font-semibold text-text">{shop.name}</p>
                  <p className="text-[11px] text-faint">{shop.slug}</p>
                </div>
              </div>
              <button type="button" className="btn btn-ghost min-h-8 min-w-8 rounded-md" aria-label="Cerrar instalación" onClick={() => setShop(null)}>
                <X size={15} aria-hidden />
              </button>
            </div>
            {shop.description && <p className="mt-2 text-xs text-muted">{shop.description}</p>}

            <dl className="mt-4 space-y-2 text-xs">
              <div className="flex justify-between gap-3">
                <dt className="text-faint">Provider</dt>
                <dd className="text-text capitalize">{shop.requires_credentials ? "Requiere credenciales" : "Zent managed"}</dd>
              </div>
              <div className="flex justify-between gap-3">
                <dt className="text-faint">Pricing</dt>
                <dd className="text-right text-text">{shop.actions.map((a) => `${a.display_name}${a.cost.price > 0 ? ` S/ ${a.cost.price}` : " (gratis)"}`).join(" · ")}</dd>
              </div>
              <div className="flex justify-between gap-3">
                <dt className="text-faint">Data</dt>
                <dd className="text-right text-text">{shop.requires_credentials ? "Secrets en SecretStore" : "Sin datos sensibles"}</dd>
              </div>
              <div className="flex justify-between gap-3">
                <dt className="text-faint">Setup</dt>
                <dd className="text-text">{shop.requires_credentials ? "Credenciales en SecretStore tras instalar" : "Sin setup"}</dd>
              </div>
            </dl>

            <label className="mt-3 block text-[11px] text-muted">
              {shop.requires_purpose ? (
                <span className="font-medium text-text">
                  Propósito de uso <span className="text-danger">*</span> — maneja datos personales
                </span>
              ) : (
                "Propósito de uso (opcional)"
              )}
              <input
                className="mt-1 w-full rounded-md border border-border bg-soft px-2 py-2 text-xs"
                placeholder="Verificación de clientes…"
                value={shopPurpose}
                onChange={(e) => setShopPurpose(e.target.value)}
                data-testid="wf-mkt-purpose"
              />
            </label>
            {shop.requires_purpose && !shopPurpose.trim() && (
              <p className="mt-1 text-[10px] text-danger" data-testid="wf-mkt-purpose-hint">
                Indica el propósito para habilitar la instalación.
              </p>
            )}

            <button
              type="button"
              className="btn btn-primary mt-5 w-full gap-1.5 text-sm"
              disabled={shopBusy || (Boolean(shop.requires_purpose) && !shopPurpose.trim())}
              data-testid="wf-mkt-install-confirm"
              onClick={() => void installFromDrawer(shop.slug)}
            >
              <Plus size={15} aria-hidden />
              {shopBusy ? "Instalando…" : "Instalar"}
            </button>
            <p className="mt-2 text-center text-[10px] text-faint">No abandonas el workflow: la capacidad queda disponible al instante.</p>
          </div>
        </div>
      )}
    </div>
  );
}

function MarketBadge({ slug }: { slug: string }) {
  const letter = slug.slice(0, 1).toUpperCase();
  return (
    <span className="flex h-9 w-9 items-center justify-center rounded-md bg-fuchsia-500/15 text-sm font-semibold text-fuchsia-400" aria-hidden>
      {letter}
    </span>
  );
}
