import { CaretLeft, ChartLineUp, Database, GearSix, MagnifyingGlass, Plus, WarningOctagon } from "@phosphor-icons/react";
import { useCallback, useEffect, useMemo, useRef, useState, type ReactNode, type RefObject } from "react";
import { api } from "../api";
import { useAuth } from "../auth";
import type { NodeBusinessSchema, NodeSchemasPayload, ParameterLevel, SelectOption } from "../lib/businessSchema";
import type { DataCatalogPayload, NodeSamples } from "../lib/dataPicker";
import { INSPECTOR_WIDTH, clampInspectorWidth } from "../lib/studioLayout";
import { useMediaQuery } from "../lib/useMediaQuery";
import type { GraphNode, NodeMeta, WorkflowGraph } from "../lib/workflowGraph";
import { makeNode, newEdgeId, prepareGraphForSave, triggerConfigOf, triggerTypeOf } from "../lib/workflowGraph";
import {
  catalogCategoryLabels,
  eventOptionsFromCatalog,
  fetchEventCatalog,
  fetchNodeCatalog,
  libraryWithCatalog,
} from "../lib/workflowCatalog";
import { NodeConfigPanel, type NodeTab } from "./NodeConfigPanel";
import { NodeLibrary, type MarketplaceContext, type MxRecommendation } from "./NodeLibrary";
import { Tooltip } from "./ui";
import {
  WorkflowCanvas,
  type CanvasChangeOptions,
  type CanvasHandle,
  type CanvasNodeAction,
  type RunOverlay,
} from "./WorkflowCanvas";
import type { RunDetail } from "./WorkflowRunInspector";
import type { Point } from "./workflowCanvas/geometry";
import { ResizeHandle } from "./workflowStudio/ResizeHandle";
import { WorkflowContextPanel } from "./workflowStudio/WorkflowContextPanel";

type TriggerType = "webhook" | "schedule" | "event";

type Props = {
  workflowId: string | null;
  graph: WorkflowGraph | null;
  onChangeGraph: (
    g: WorkflowGraph,
    triggerType: TriggerType,
    triggerConfig: Record<string, unknown>,
    options?: CanvasChangeOptions,
  ) => void;
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
  /** Alto del editor (el estudio lo pone a viewport). */
  heightClass?: string;
  canvasRef?: RefObject<CanvasHandle | null>;
  /** Clave de persistencia del viewport (usuario + workflow). */
  viewportKey?: string | null;
  /** Panel inferior bajo el lienzo (simulador). */
  bottomPanel?: ReactNode;
  /** `focus`: solo lienzo y barra flotante. */
  chrome?: "full" | "focus";
  toolbarExtra?: ReactNode;
  inspectorWidth?: number;
  onInspectorWidthChange?: (width: number) => void;
  minimap?: boolean;
  onToggleMinimap?: () => void;
  /** "Configurar" en modo enfoque sale del modo para mostrar el inspector. */
  onExitFocus?: () => void;
};

const RAIL_INSET = 60;
const FLYOUT_W = 304;
const OVERLAY_INSPECTOR_W = 380;

function RailButton({
  label,
  shortcut,
  pressed,
  expanded,
  testId,
  onClick,
  children,
}: {
  label: string;
  shortcut?: string;
  pressed?: boolean;
  expanded?: boolean;
  testId: string;
  onClick: () => void;
  children: ReactNode;
}) {
  return (
    <Tooltip label={shortcut ? `${label} · ${shortcut}` : label} side="right">
      <button
        type="button"
        aria-label={label}
        aria-pressed={pressed}
        aria-expanded={expanded}
        data-testid={testId}
        onClick={onClick}
        className={`flex h-9 w-9 cursor-pointer items-center justify-center rounded-md outline-none transition-colors focus-visible:ring-2 focus-visible:ring-accent ${
          pressed ? "bg-accent/15 text-accent" : "text-muted hover:bg-soft hover:text-text"
        }`}
      >
        {children}
      </button>
    </Tooltip>
  );
}

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
  canvasRef,
  viewportKey,
  bottomPanel,
  chrome = "full",
  toolbarExtra,
  inspectorWidth = INSPECTOR_WIDTH.initial,
  onInspectorWidthChange,
  minimap = true,
  onToggleMinimap,
  onExitFocus,
}: Props) {
  const { session } = useAuth();
  const innerCanvasRef = useRef<CanvasHandle | null>(null);
  const canvas = canvasRef ?? innerCanvasRef;
  const wide = useMediaQuery("(min-width: 1280px)", true);
  const [leftPanel, setLeftPanel] = useState<"catalog" | "context" | null>(null);
  const [inspectorCollapsed, setInspectorCollapsed] = useState(false);
  const [tabRequest, setTabRequest] = useState<{ tab: NodeTab; key: number } | null>(null);
  const insertAt = useRef<Point | null>(null);
  const [viewportW, setViewportW] = useState(() => (typeof window === "undefined" ? 1440 : window.innerWidth));
  const [selectedEdge, setSelectedEdge] = useState<string | null>(null);
  const [nodeSchemas, setNodeSchemas] = useState<Record<string, NodeBusinessSchema> | null>(null);
  const [catalogNodes, setCatalogNodes] = useState<Record<string, NodeMeta> | null>(null);
  const [categoryLabels, setCategoryLabels] = useState<Record<string, string> | null>(null);
  const [eventOptions, setEventOptions] = useState<SelectOption[] | null>(null);
  const [samples, setSamples] = useState<NodeSamples | null>(null);
  const [dataCatalog, setDataCatalog] = useState<DataCatalogPayload | null>(null);
  const [mxInstalls, setMxInstalls] = useState<{ id: string; integration: { slug: string; name: string } }[]>([]);
  const [mxActions, setMxActions] = useState<Record<string, { action_id: string; display_name: string }[]>>({});
  const [mkt, setMkt] = useState<MarketplaceContext | null>(null);
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
  const [nodeIssues, setNodeIssues] = useState<Record<string, { status: string; message: string }> | undefined>(undefined);

  // Readiness por nodo (workflow portability): badges verde/amarillo/rojo en el
  // canvas. Se refresca cuando el estudio pinta un overlay nuevo.
  useEffect(() => {
    if (!session || !workflowId) {
      setNodeIssues(undefined);
      return;
    }
    let alive = true;
    api<{ node_issues?: Record<string, { status: string; message: string }> }>(
      `/api/v1/workflows/${workflowId}/readiness`,
      { token: session.token, organizationId: session.organizationId }
    )
      .then((d) => {
        if (alive) setNodeIssues(d.node_issues ?? {});
      })
      .catch(() => {
        if (alive) setNodeIssues(undefined);
      });
    return () => {
      alive = false;
    };
  }, [session, workflowId, overlay]);

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

  // Catálogo de eventos en lenguaje de negocio. El selector del trigger y de
  // `wait_event` lo usa; sin endpoint cae a `EVENTS_OPTIONS` local.
  useEffect(() => {
    if (!session) return;
    let alive = true;
    void fetchEventCatalog(
      <T,>(path: string) =>
        api<T>(path, { token: session.token, organizationId: session.organizationId }),
      session.organizationId,
    ).then((payload) => {
      if (alive) setEventOptions(payload ? eventOptionsFromCatalog(payload) : null);
    });
    return () => {
      alive = false;
    };
  }, [session]);

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
  function insertNode(nodeType: string, config?: Record<string, unknown>, at?: Point | null) {
    if (!graph) return;
    const source =
      graph.nodes.find((n) => n.id === selectedNodeId && n.output_ports.length > 0) ??
      graph.nodes.find((n) => n.type.startsWith("trigger_")) ??
      null;

    const target = at ?? insertAt.current;
    insertAt.current = null;
    const spawn = target
      ? { x: Math.round(target.x), y: Math.round(target.y) }
      : source
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
    onChangeGraph(copy, triggerTypeOf(copy), triggerConfigOf(copy), { checkpoint: true });
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

  function addRecommendation(rec: MxRecommendation) {
    const installed = mkt?.installed.find((item) => item.integration.slug === rec.integration_slug);
    const action = installed?.actions.find((item) => item.action_id === rec.action_id);
    if (!installed || !action) return;
    addMarketplaceAction(installed.install_id, action);
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
  const focus = chrome === "focus";
  const hasSelection = Boolean(selectedNodeObj || selectedEdgeObj);
  const inspectorOpen = hasSelection && !inspectorCollapsed && !focus;
  const docked = wide;
  const dockedWidth = clampInspectorWidth(inspectorWidth, viewportW);
  const leftInset = focus ? 0 : RAIL_INSET + (leftPanel ? FLYOUT_W + 8 : 0);
  const rightInset = inspectorOpen && !docked ? Math.min(OVERLAY_INSPECTOR_W, viewportW - 120) + 16 : 0;

  useEffect(() => {
    const onResize = () => setViewportW(window.innerWidth);
    window.addEventListener("resize", onResize);
    return () => window.removeEventListener("resize", onResize);
  }, []);

  // Selección nueva: el inspector vuelve a abrirse. En pantallas reducidas el
  // catálogo y el inspector no conviven.
  useEffect(() => {
    if (!selectedNodeId) return;
    setInspectorCollapsed(false);
    if (!wide) setLeftPanel(null);
  }, [selectedNodeId, wide]);

  useEffect(() => {
    if (selectedEdge) setInspectorCollapsed(false);
  }, [selectedEdge]);

  function toggleLeftPanel(next: "catalog" | "context") {
    setLeftPanel((cur) => {
      const value = cur === next ? null : next;
      if (value && !wide) setInspectorCollapsed(true);
      return value;
    });
  }

  const handleNodeAction = useCallback(
    (action: CanvasNodeAction, nodeId: string) => {
      if (focus) onExitFocus?.();
      onSelectNode(nodeId);
      setSelectedEdge(null);
      setInspectorCollapsed(false);
      setTabRequest({ tab: action === "run_node" ? "run" : "config", key: Date.now() });
    },
    [focus, onExitFocus, onSelectNode],
  );

  function openCanvasSearch() {
    canvas.current?.openSearch();
  }

  const requestAddNode = useCallback(
    (world: Point | null) => {
      insertAt.current = world;
      setLeftPanel("catalog");
      if (!wide) setInspectorCollapsed(true);
    },
    [wide],
  );

  useEffect(() => {
    if (focus) return;
    function onKey(ev: KeyboardEvent) {
      if (ev.ctrlKey || ev.metaKey || ev.altKey || (ev.key !== "n" && ev.key !== "N")) return;
      const t = ev.target as HTMLElement | null;
      if (t && (t.tagName === "INPUT" || t.tagName === "TEXTAREA" || t.tagName === "SELECT" || t.isContentEditable)) return;
      if (t?.closest?.('[role="dialog"],[role="menu"]')) return;
      ev.preventDefault();
      requestAddNode(null);
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [focus, requestAddNode]);

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

  const inspector =
    local && (selectedNodeObj || selectedEdgeObj) ? (
      <NodeConfigPanel
        className="h-full w-full rounded-none border-0 shadow-none"
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
        onCollapse={() => setInspectorCollapsed(true)}
        tabRequest={tabRequest}
        nodeIssue={selectedNodeObj ? nodeIssues?.[selectedNodeObj.id] ?? null : null}
        onFocusNode={(id) => {
          onSelectNode(id);
          canvas.current?.centerNode(id);
        }}
        kbs={kbs}
        agents={agents}
        mxInstalls={mxInstalls}
        mxActions={mxActions}
        nodeSchemas={nodeSchemas}
        catalogNodes={catalogNodes}
        eventOptions={eventOptions}
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
        onAddSuggested={insertNode}
      />
    ) : null;

  return (
    <div className={`flex min-h-0 min-w-0 ${heightClass}`} data-testid="workflow-canvas-editor" data-chrome={chrome}>
      <div className="flex min-h-0 min-w-0 flex-1 flex-col">
      <div className="relative min-h-0 min-w-0 flex-1">
        {local ? (
          <WorkflowCanvas
            key={workflowId ?? "draft"}
            ref={canvas}
            className="h-full"
            graph={local}
            agents={agents}
            onChange={(g, options) => onChangeGraph(g, triggerTypeOf(g), triggerConfigOf(g), options)}
            selectedNodeId={selectedNodeId}
            onSelectNode={onSelectNode}
            selectedEdgeId={selectedEdge}
            onSelectEdge={setSelectedEdge}
            overlay={overlay}
            leftInset={leftInset}
            rightInset={rightInset}
            nodeIssues={nodeIssues}
            viewportKey={viewportKey}
            minimap={minimap}
            onToggleMinimap={onToggleMinimap}
            onRequestAddNode={focus ? undefined : requestAddNode}
            onDropNode={(type, world) => insertNode(type, undefined, world)}
            onNodeAction={handleNodeAction}
            toolbarExtra={toolbarExtra}
          />
        ) : (
          <div className="flex h-full w-full items-center justify-center border border-dashed border-border bg-soft/30 text-xs text-faint">
            {workflowId ? "Cargando grafo…" : "Guarda el workflow para empezar a editar su canvas."}
          </div>
        )}

        {!focus && (
          <nav
            className="absolute top-3 left-3 z-20 flex flex-col gap-1 rounded-lg border border-border bg-raised/95 p-1 shadow-pop backdrop-blur-sm"
            aria-label="Herramientas del lienzo"
            data-testid="wf-canvas-rail"
          >
            <RailButton
              label="Añadir nodo"
              shortcut="N"
              pressed={leftPanel === "catalog"}
              expanded={leftPanel === "catalog"}
              testId="wf-rail-add"
              onClick={() => toggleLeftPanel("catalog")}
            >
              <Plus size={17} aria-hidden />
            </RailButton>
            <RailButton label="Buscar en el lienzo" shortcut="Ctrl + F" testId="wf-rail-search" onClick={openCanvasSearch}>
              <MagnifyingGlass size={17} aria-hidden />
            </RailButton>
            <RailButton
              label="Contexto y datos"
              pressed={leftPanel === "context"}
              expanded={leftPanel === "context"}
              testId="wf-context-toggle"
              onClick={() => toggleLeftPanel("context")}
            >
              <Database size={17} aria-hidden />
            </RailButton>
            {hasSelection && inspectorCollapsed && (
              <RailButton label="Mostrar configuración del nodo" testId="wf-inspector-expand" onClick={() => setInspectorCollapsed(false)}>
                <GearSix size={17} aria-hidden />
              </RailButton>
            )}
          </nav>
        )}

        {!focus && leftPanel === "catalog" && (
          <div className="absolute top-3 bottom-3 z-30 flex" style={{ left: RAIL_INSET, width: `min(${FLYOUT_W}px, calc(100% - ${RAIL_INSET + 12}px))` }}>
            <NodeLibrary
              className="h-full w-full shadow-pop"
              autoFocus
              onClose={() => setLeftPanel(null)}
              usedTypes={local ? local.nodes.map((n) => n.type) : []}
              nodes={catalogNodes}
              categoryLabels={categoryLabels}
              businessMode={configLevel !== "advanced"}
              onAdd={(meta) => insertNode(meta.type)}
              marketplace={mkt}
              onAddMarketplaceAction={addMarketplaceAction}
              onAddRecommendation={addRecommendation}
              returnTo={workflowId ? `/workflows/${workflowId}` : "/workflows/new/manual"}
              nodeId={selectedNodeId}
            />
          </div>
        )}

        {isEmptyCanvas && !focus && (
          <div
            className="absolute top-3 z-20 w-[min(340px,calc(100%-6rem))] rounded-lg border border-accent/30 bg-surface/95 p-3 shadow-panel backdrop-blur-sm"
            style={{ left: leftInset + 8 }}
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

        {cost && cost.calls_per_run > 0 && !isEmptyCanvas && !focus && (
          <div
            className="pointer-events-none absolute top-3 z-20 flex max-w-[50%] flex-wrap justify-end gap-1.5 [&>*]:pointer-events-auto"
            style={{ right: 12 + rightInset }}
          >
            <span
              className="inline-flex items-center gap-1 rounded-md border border-border bg-surface/95 px-2 py-1 text-[11px] text-muted"
              data-testid="wf-cost"
              title={`${cost.calls_per_run} llamadas por run`}
            >
              <ChartLineUp size={12} aria-hidden />~ S/ {cost.per_run.toFixed(2)} / run · S/ {cost.monthly.toFixed(2)} / mes
            </span>
            {cost.bulk_warning && (
              <span
                className="inline-flex items-center gap-1 rounded-md border border-danger/40 bg-danger-soft px-2 py-1 text-[11px] text-danger"
                data-testid="wf-bulk-warning"
              >
                <WarningOctagon size={12} aria-hidden />
                {cost.calls_per_run} llamadas pagadas por run
              </span>
            )}
            {(cost.warnings ?? []).slice(0, 2).map((warning) => (
              <span
                key={warning.code}
                className="inline-flex items-center gap-1 rounded-md border border-warn/40 bg-warn-soft px-2 py-1 text-[11px] text-warn"
                data-testid={`wf-cost-warning-${warning.code}`}
                title={warning.message}
              >
                <WarningOctagon size={12} aria-hidden />
                {warning.message}
              </span>
            ))}
          </div>
        )}

        {!focus && leftPanel === "context" && (
          <div
            className="absolute top-3 bottom-3 z-30 flex"
            style={{ left: RAIL_INSET, width: `min(${FLYOUT_W + 36}px, calc(100% - ${RAIL_INSET + 12}px))` }}
          >
            <WorkflowContextPanel
              sources={dataCatalog?.sources}
              contributions={run?.contributions}
              nodes={catalogNodes}
              used={(run?.contributions ?? []).slice(0, 12).map((item) => ({
                plane: item.section,
                source: item.node_id || item.section,
                label: item.payload?.label ? String(item.payload.label) : item.section,
                scope: item.node_type || undefined,
              }))}
              mapping={
                local?.metadata?.data_mapping && typeof local.metadata.data_mapping === "object"
                  ? (local.metadata.data_mapping as {
                      mappings?: { source_id: string; field: string; target: string }[];
                      memory?: { enabled?: boolean };
                    })
                  : null
              }
              onMemoryEnabledChange={(enabled) => {
                if (!local) return;
                const current =
                  local.metadata?.data_mapping && typeof local.metadata.data_mapping === "object"
                    ? (local.metadata.data_mapping as Record<string, unknown>)
                    : {};
                const memory =
                  current.memory && typeof current.memory === "object"
                    ? { ...(current.memory as Record<string, unknown>), enabled }
                    : { enabled };
                onChangeGraph(
                  {
                    ...local,
                    metadata: {
                      ...local.metadata,
                      data_mapping: { ...current, memory },
                    },
                  },
                  triggerTypeOf(local),
                  triggerConfigOf(local),
                );
              }}
              onClose={() => setLeftPanel(null)}
            />
          </div>
        )}

        {inspectorOpen && !docked && inspector && (
          <div
            className="absolute top-3 right-3 bottom-3 z-30 flex overflow-hidden rounded-lg border border-border bg-surface shadow-pop"
            style={{ width: `min(${OVERLAY_INSPECTOR_W}px, calc(100% - ${RAIL_INSET + 24}px))` }}
            data-testid="wf-inspector"
            data-docked="false"
          >
            {inspector}
          </div>
        )}
      </div>
      {bottomPanel && <div className={focus ? "hidden" : "contents"}>{bottomPanel}</div>}
      </div>

      {inspectorOpen && docked && inspector && (
        <aside
          className="relative flex min-h-0 shrink-0 border-l border-border bg-surface"
          style={{ width: dockedWidth }}
          data-testid="wf-inspector"
          data-docked="true"
          aria-label="Configuración del nodo"
        >
          <ResizeHandle
            axis="x"
            value={dockedWidth}
            min={INSPECTOR_WIDTH.min}
            max={clampInspectorWidth(INSPECTOR_WIDTH.max, viewportW)}
            resetTo={INSPECTOR_WIDTH.initial}
            onChange={(width) => onInspectorWidthChange?.(width)}
            label="Ancho del panel de configuración"
            testId="wf-inspector-resize"
          />
          {inspector}
        </aside>
      )}
      {hasSelection && inspectorCollapsed && docked && !focus && (
        <div className="flex w-10 shrink-0 flex-col items-center border-l border-border bg-surface pt-2">
          <Tooltip label="Mostrar configuración del nodo" side="left">
            <button
              type="button"
              aria-label="Mostrar configuración del nodo"
              className="flex h-8 w-8 cursor-pointer items-center justify-center rounded-md text-muted hover:bg-soft hover:text-text"
              onClick={() => setInspectorCollapsed(false)}
            >
              <CaretLeft size={15} aria-hidden />
            </button>
          </Tooltip>
        </div>
      )}
    </div>
  );
}
