import { Copy, Crosshair, GearSix, MagnifyingGlass, Play, Plus, SelectionAll, Trash, TreeStructure } from "@phosphor-icons/react";
import {
  useCallback,
  useEffect,
  useImperativeHandle,
  useLayoutEffect,
  useMemo,
  useRef,
  useState,
  type DragEvent,
  type KeyboardEvent as ReactKeyboardEvent,
  type MouseEvent as ReactMouseEvent,
  type PointerEvent as ReactPointerEvent,
  type ReactNode,
  type Ref,
} from "react";
import { canvasNodeKind } from "../lib/canvasNodeKind";
import {
  NODE_H,
  NODE_W,
  centerOn,
  clampZoom,
  detailLevel,
  fitRect,
  loadViewport,
  nodesBounds,
  rectFromPoints,
  rectsIntersect,
  revealRect,
  saveViewport,
  visibleWorldRect,
  wheelIntent,
  zoomAt,
  type Viewport,
} from "../lib/canvasViewport";
import { autoLayout, graphDirection, type LayoutDirection } from "../lib/graphAutoLayout";
import type { GraphEdge, GraphNode, WorkflowGraph } from "../lib/workflowGraph";
import { newGraphNodeId, portCompatible } from "../lib/workflowGraph";
import { CanvasContextMenu, type ContextMenuItem } from "./workflowCanvas/CanvasContextMenu";
import { CanvasEdges } from "./workflowCanvas/CanvasEdges";
import { CanvasMinimap } from "./workflowCanvas/CanvasMinimap";
import { CanvasNode, type NodeHandlers, type RunMark } from "./workflowCanvas/CanvasNode";
import { CanvasSearch } from "./workflowCanvas/CanvasSearch";
import { CanvasToolbar } from "./workflowCanvas/CanvasToolbar";
import { NODE_DND_TYPE, portPoint, wirePath, type Point, type Positions } from "./workflowCanvas/geometry";

export type RunOverlay = Record<string, RunMark>;

export type CanvasChangeOptions = {
  /** Cierra el paso de historial actual: el cambio se deshace por separado. */
  checkpoint?: boolean;
};

export type CanvasHandle = {
  fitView: () => void;
  fitSelection: () => void;
  centerNode: (id: string) => void;
  zoomBy: (factor: number) => void;
  resetZoom: () => void;
  getViewport: () => Viewport;
  setViewport: (view: Viewport) => void;
  openSearch: () => void;
  autoLayout: (direction: LayoutDirection) => void;
  /** Punto de mundo en el centro del área visible (para insertar nodos ahí). */
  centerWorld: () => Point;
};

export type CanvasNodeAction = "configure" | "run_node";

type Props = {
  graph: WorkflowGraph;
  onChange: (graph: WorkflowGraph, options?: CanvasChangeOptions) => void;
  selectedNodeId: string | null;
  onSelectNode: (id: string | null) => void;
  selectedEdgeId: string | null;
  onSelectEdge: (id: string | null) => void;
  overlay?: RunOverlay;
  /** Nombres reales de agentes: el nodo `llm` no debe mostrar un UUID. */
  agents?: { id: string; name: string }[];
  className?: string;
  /** Ancho tapado a la derecha por un overlay: el nodo elegido se aparta y los encuadres lo descuentan. */
  rightInset?: number;
  /** Ancho tapado a la izquierda (rail/catálogo flotante). */
  leftInset?: number;
  /** Readiness por nodo (workflow portability): verde/amarillo/rojo en el nodo. */
  nodeIssues?: Record<string, { status: string; message: string }>;
  ref?: Ref<CanvasHandle>;
  /** Clave de localStorage del viewport (usuario + workflow). Sin clave no persiste. */
  viewportKey?: string | null;
  minimap?: boolean;
  onToggleMinimap?: () => void;
  /** "Añadir nodo aquí" (menú contextual) o desde el lienzo vacío. */
  onRequestAddNode?: (world: Point | null) => void;
  /** Soltar un nodo arrastrado desde el catálogo. */
  onDropNode?: (type: string, world: Point) => void;
  onNodeAction?: (action: CanvasNodeAction, nodeId: string) => void;
  /** Controles extra al inicio de la barra flotante (p. ej. modo enfoque). */
  toolbarExtra?: ReactNode;
  showToolbar?: boolean;
};

type DragState = {
  ids: string[];
  /** Nodo pulsado: un clic sin arrastre dentro de una selección múltiple la reduce a él. */
  origin: string;
  collapse: boolean;
  startX: number;
  startY: number;
  dx: number;
  dy: number;
  moved: boolean;
};
type Marquee = { x0: number; y0: number; x1: number; y1: number; additive: boolean };
type Wire = { fromNode: string; fromPort: string; x2: number; y2: number };
type MenuState = { x: number; y: number; nodeId: string | null; world: Point };
type PanGesture = { x: number; y: number; sx: number; sy: number; moved: boolean; clear: boolean };

const CULL_THRESHOLD = 150;
const CULL_MARGIN = 400;
const NUDGE = 8;

function useStableHandler<A extends unknown[], R>(fn: (...args: A) => R): (...args: A) => R {
  const ref = useRef(fn);
  useLayoutEffect(() => {
    ref.current = fn;
  });
  return useCallback((...args: A) => ref.current(...args), []);
}

function safePoint(p: { x: number; y: number } | undefined): Point {
  return {
    x: Number.isFinite(p?.x) ? (p as Point).x : 0,
    y: Number.isFinite(p?.y) ? (p as Point).y : 0,
  };
}

function isEditable(el: Element | null): boolean {
  if (!el) return false;
  const tag = el.tagName;
  return tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT" || (el as HTMLElement).isContentEditable;
}

/**
 * Lienzo del workflow: pan/zoom con rueda y trackpad, encuadres, selección
 * múltiple (clic con modificador o área), arrastre de grupo, menú contextual,
 * búsqueda, minimapa y zoom semántico. Las posiciones arrastradas se aplican
 * localmente y se confirman en el grafo una sola vez al soltar.
 */
export function WorkflowCanvas({
  graph,
  onChange,
  selectedNodeId,
  onSelectNode,
  selectedEdgeId,
  onSelectEdge,
  overlay,
  agents,
  className = "h-[560px]",
  rightInset = 0,
  leftInset = 0,
  nodeIssues,
  ref,
  viewportKey,
  minimap = false,
  onToggleMinimap,
  onRequestAddNode,
  onDropNode,
  onNodeAction,
  toolbarExtra,
  showToolbar = true,
}: Props) {
  const hostRef = useRef<HTMLDivElement>(null);
  const [view, setView] = useState<Viewport>({ x: 60, y: 40, s: 1 });
  const [host, setHost] = useState({ w: 0, h: 0 });
  const [selection, setSelection] = useState<string[]>(() => (selectedNodeId ? [selectedNodeId] : []));
  const [drag, setDrag] = useState<DragState | null>(null);
  const [marquee, setMarquee] = useState<Marquee | null>(null);
  const [wire, setWire] = useState<Wire | null>(null);
  const [hotPort, setHotPort] = useState<{ node: string; port: string; side: "in" | "out" } | null>(null);
  const [menu, setMenu] = useState<MenuState | null>(null);
  const [searchOpen, setSearchOpen] = useState(false);
  const [dropActive, setDropActive] = useState(false);
  const initialized = useRef(false);
  const pendingFit = useRef(false);
  const panRef = useRef<PanGesture | null>(null);
  const draggingRef = useRef(false);
  const viewRef = useRef(view);

  useLayoutEffect(() => {
    viewRef.current = view;
  }, [view]);

  const direction = graphDirection(graph);
  const nodesById = useMemo(() => new Map(graph.nodes.map((n) => [n.id, n])), [graph.nodes]);
  const selectionSet = useMemo(() => new Set(selection.filter((id) => nodesById.has(id))), [selection, nodesById]);
  const dragSet = useMemo(() => (drag?.moved ? new Set(drag.ids) : null), [drag]);

  const positions: Positions = useMemo(() => {
    const map: Positions = new Map();
    for (const n of graph.nodes) {
      const p = safePoint(n.position);
      map.set(n.id, dragSet?.has(n.id) && drag ? { x: p.x + drag.dx, y: p.y + drag.dy } : p);
    }
    return map;
  }, [graph.nodes, drag, dragSet]);

  const agentNames = useMemo(() => new Map((agents ?? []).map((a) => [a.id, a.name])), [agents]);

  // -- Tamaño del host ---------------------------------------------------------
  useLayoutEffect(() => {
    const el = hostRef.current;
    if (!el) return;
    const measure = () => setHost((cur) => (cur.w === el.clientWidth && cur.h === el.clientHeight ? cur : { w: el.clientWidth, h: el.clientHeight }));
    measure();
    const ro = new ResizeObserver(measure);
    ro.observe(el);
    return () => ro.disconnect();
  }, []);

  const hostSize = useCallback(() => {
    const el = hostRef.current;
    return { w: el?.clientWidth ?? host.w, h: el?.clientHeight ?? host.h };
  }, [host]);

  const fitView = useStableHandler(() => {
    const bounds = nodesBounds(graph.nodes);
    if (!bounds) return;
    setView(fitRect(bounds, hostSize(), { insets: { left: leftInset, right: rightInset, bottom: 56 } }));
  });

  // -- Viewport inicial: el guardado del usuario o un encuadre, una sola vez ----
  useEffect(() => {
    if (initialized.current || host.w === 0 || graph.nodes.length === 0) return;
    initialized.current = true;
    const stored = loadViewport(viewportKey);
    if (stored) setView(stored);
    else fitView();
  }, [host.w, graph.nodes.length, viewportKey, fitView]);

  useEffect(() => {
    if (!initialized.current || !viewportKey) return;
    const t = window.setTimeout(() => saveViewport(viewportKey, view), 250);
    return () => window.clearTimeout(t);
  }, [view, viewportKey]);

  // Tras "organizar" el grafo, encuadrar el resultado (acción explícita del usuario).
  useEffect(() => {
    if (!pendingFit.current) return;
    pendingFit.current = false;
    fitView();
  }, [graph.nodes, fitView]);

  // -- Selección: el padre manda el nodo principal; aquí vive la múltiple -------
  useEffect(() => {
    setSelection((cur) => {
      if (selectedNodeId == null) return cur.length > 1 ? cur : cur.length ? [] : cur;
      return cur.includes(selectedNodeId) ? cur : [selectedNodeId];
    });
  }, [selectedNodeId]);

  // El inspector puede tapar el nodo elegido: desplazar lo justo (sin cambiar zoom).
  const revealNode = useStableHandler((id: string) => {
    const p = positions.get(id);
    if (!p) return;
    setView((v) => revealRect(v, { x: p.x, y: p.y, w: NODE_W, h: NODE_H }, hostSize(), rightInset));
  });

  useEffect(() => {
    if (!selectedNodeId || draggingRef.current) return;
    revealNode(selectedNodeId);
    // Solo al cambiar la selección o el overlay: mover nodos no debe reencuadrar.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedNodeId, rightInset]);

  const toWorld = useCallback((clientX: number, clientY: number): Point => {
    const rect = hostRef.current?.getBoundingClientRect();
    const v = viewRef.current;
    if (!rect) return { x: 0, y: 0 };
    return { x: (clientX - rect.left - v.x) / v.s, y: (clientY - rect.top - v.y) / v.s };
  }, []);

  // -- Acciones de navegación -------------------------------------------------
  const zoomBy = useStableHandler((factor: number) => {
    const size = hostSize();
    setView((v) => zoomAt(v, size.w / 2, size.h / 2, v.s * factor));
  });

  const resetZoom = useStableHandler(() => {
    const size = hostSize();
    setView((v) => zoomAt(v, size.w / 2, size.h / 2, 1));
  });

  const fitSelection = useStableHandler(() => {
    const ids = selectionSet.size ? [...selectionSet] : selectedNodeId ? [selectedNodeId] : [];
    const nodes = ids.map((id) => nodesById.get(id)).filter((n): n is GraphNode => !!n);
    const bounds = nodesBounds(nodes.map((n) => ({ position: positions.get(n.id)! })));
    if (!bounds) return;
    setView(fitRect(bounds, hostSize(), { maxZoom: 1.25, padding: 72, insets: { left: leftInset, right: rightInset, bottom: 56 } }));
  });

  const centerNode = useStableHandler((id: string) => {
    const p = positions.get(id);
    if (!p) return;
    const size = hostSize();
    const usable = { w: size.w - rightInset - leftInset, h: size.h };
    setView((v) => {
      const s = v.s < 0.6 ? 0.9 : v.s;
      const next = centerOn(v, p.x + NODE_W / 2, p.y + NODE_H / 2, usable, s);
      return { ...next, x: next.x + leftInset };
    });
  });

  const runAutoLayout = useStableHandler((dir: LayoutDirection) => {
    if (graph.nodes.length === 0) return;
    pendingFit.current = true;
    onChange(autoLayout(graph, dir).graph, { checkpoint: true });
  });

  useImperativeHandle(
    ref,
    () => ({
      fitView,
      fitSelection,
      centerNode,
      zoomBy,
      resetZoom,
      getViewport: () => viewRef.current,
      setViewport: (v) => setView({ ...v, s: clampZoom(v.s) }),
      openSearch: () => setSearchOpen(true),
      autoLayout: runAutoLayout,
      centerWorld: () => {
        const size = hostSize();
        const v = viewRef.current;
        return { x: (leftInset + (size.w - leftInset - rightInset) / 2 - v.x) / v.s, y: (size.h / 2 - v.y) / v.s };
      },
    }),
    [fitView, fitSelection, centerNode, zoomBy, resetZoom, runAutoLayout, hostSize, leftInset, rightInset],
  );

  // -- Edición -----------------------------------------------------------------
  const selectOnly = useStableHandler((ids: string[]) => {
    setSelection(ids);
    onSelectEdge(null);
    onSelectNode(ids.length === 1 ? ids[0] : null);
  });

  const deleteSelection = useStableHandler(() => {
    const ids = selectionSet.size ? selectionSet : selectedNodeId ? new Set([selectedNodeId]) : null;
    if (ids && ids.size) {
      onChange(
        {
          ...graph,
          nodes: graph.nodes.filter((n) => !ids.has(n.id)),
          edges: graph.edges.filter((e) => !ids.has(e.from_node) && !ids.has(e.to_node)),
          entrypoints: graph.entrypoints.filter((e) => !ids.has(e)),
        },
        { checkpoint: true },
      );
      setSelection([]);
      onSelectNode(null);
    } else if (selectedEdgeId) {
      onChange({ ...graph, edges: graph.edges.filter((e) => e.id !== selectedEdgeId) }, { checkpoint: true });
      onSelectEdge(null);
    }
  });

  const duplicateSelection = useStableHandler(() => {
    const ids = selectionSet.size ? [...selectionSet] : [];
    if (!ids.length) return;
    const idMap = new Map(ids.map((id) => [id, newGraphNodeId()]));
    const copies: GraphNode[] = ids.map((id) => {
      const n = nodesById.get(id)!;
      const p = safePoint(n.position);
      return { ...structuredClone(n), id: idMap.get(id)!, position: { x: p.x + 40, y: p.y + 40 } };
    });
    const edgeCopies: GraphEdge[] = graph.edges
      .filter((e) => idMap.has(e.from_node) && idMap.has(e.to_node))
      .map((e, i) => ({
        ...e,
        id: `e${Date.now().toString(36)}d${i}`,
        from_node: idMap.get(e.from_node)!,
        to_node: idMap.get(e.to_node)!,
      }));
    onChange({ ...graph, nodes: [...graph.nodes, ...copies], edges: [...graph.edges, ...edgeCopies] }, { checkpoint: true });
    selectOnly(copies.map((c) => c.id));
  });

  const nudgeSelection = useStableHandler((dx: number, dy: number) => {
    if (!selectionSet.size) {
      setView((v) => ({ ...v, x: v.x - dx * 6, y: v.y - dy * 6 }));
      return;
    }
    onChange({
      ...graph,
      nodes: graph.nodes.map((n) => {
        if (!selectionSet.has(n.id)) return n;
        const p = safePoint(n.position);
        return { ...n, position: { x: p.x + dx, y: p.y + dy } };
      }),
    });
  });

  // -- Puntero -----------------------------------------------------------------
  function onHostPointerDown(ev: ReactPointerEvent<HTMLDivElement>) {
    if ((ev.button !== 0 && ev.button !== 1) || wire) return;
    setMenu(null);
    hostRef.current?.focus({ preventScroll: true });
    ev.currentTarget.setPointerCapture?.(ev.pointerId);
    if (ev.button === 0 && ev.shiftKey) {
      const w = toWorld(ev.clientX, ev.clientY);
      setMarquee({ x0: w.x, y0: w.y, x1: w.x, y1: w.y, additive: ev.ctrlKey || ev.metaKey });
      return;
    }
    panRef.current = {
      x: ev.clientX,
      y: ev.clientY,
      sx: view.x,
      sy: view.y,
      moved: false,
      clear: ev.button === 0 && !ev.ctrlKey && !ev.metaKey,
    };
  }

  const onNodePointerDown = useStableHandler((ev: ReactPointerEvent<HTMLDivElement>, id: string) => {
    if (ev.button !== 0 || wire) return;
    ev.stopPropagation();
    setMenu(null);
    ev.currentTarget.focus({ preventScroll: true });
    // Captura: el inspector que aparece al seleccionar no debe robar el pointermove.
    ev.currentTarget.setPointerCapture?.(ev.pointerId);
    let ids: string[];
    let collapse = false;
    if (ev.shiftKey || ev.ctrlKey || ev.metaKey) {
      ids = selectionSet.has(id) ? [...selectionSet].filter((x) => x !== id) : [...selectionSet, id];
      setSelection(ids);
      onSelectEdge(null);
      onSelectNode(ids.length === 1 ? ids[0] : null);
      if (!ids.includes(id)) return;
    } else if (selectionSet.has(id) && selectionSet.size > 1) {
      ids = [...selectionSet];
      collapse = true;
    } else {
      ids = [id];
      selectOnly(ids);
    }
    draggingRef.current = true;
    setDrag({ ids, origin: id, collapse, startX: ev.clientX, startY: ev.clientY, dx: 0, dy: 0, moved: false });
  });

  const onPortDown = useStableHandler((ev: ReactPointerEvent<HTMLSpanElement>, id: string, port: string) => {
    ev.stopPropagation();
    if (ev.button !== 0) return;
    hostRef.current?.setPointerCapture?.(ev.pointerId);
    const w = toWorld(ev.clientX, ev.clientY);
    setWire({ fromNode: id, fromPort: port, x2: w.x, y2: w.y });
    setHotPort({ node: id, port, side: "out" });
  });

  function onPointerMove(ev: ReactPointerEvent<HTMLDivElement>) {
    if (wire) {
      const w = toWorld(ev.clientX, ev.clientY);
      setWire((cur) => (cur ? { ...cur, x2: w.x, y2: w.y } : cur));
      const el = document.elementFromPoint(ev.clientX, ev.clientY) as HTMLElement | null;
      const target = el?.closest<HTMLElement>("[data-port-name]");
      setHotPort(
        target
          ? { node: target.dataset.node!, port: target.dataset.portName ?? "in", side: (target.dataset.side as "in" | "out") ?? "in" }
          : null,
      );
      return;
    }
    const pan = panRef.current;
    if (pan) {
      const dx = ev.clientX - pan.x;
      const dy = ev.clientY - pan.y;
      if (!pan.moved && Math.hypot(dx, dy) > 3) pan.moved = true;
      if (pan.moved) setView((v) => ({ ...v, x: pan.sx + dx, y: pan.sy + dy }));
      return;
    }
    if (marquee) {
      const w = toWorld(ev.clientX, ev.clientY);
      setMarquee((m) => (m ? { ...m, x1: w.x, y1: w.y } : m));
      return;
    }
    if (drag) {
      const dx = (ev.clientX - drag.startX) / view.s;
      const dy = (ev.clientY - drag.startY) / view.s;
      const moved = drag.moved || Math.hypot(ev.clientX - drag.startX, ev.clientY - drag.startY) > 3;
      setDrag({ ...drag, dx, dy, moved });
    }
  }

  function connectWire() {
    if (!wire || !hotPort || hotPort.side !== "in") return;
    const from = nodesById.get(wire.fromNode);
    const target = nodesById.get(hotPort.node);
    const fromPort = from?.output_ports.find((p) => p.name === wire.fromPort);
    const toPort = target?.input_ports.find((p) => p.name === hotPort.port);
    const dup = graph.edges.some(
      (e) => e.from_node === wire.fromNode && e.from_port === wire.fromPort && e.to_node === hotPort.node,
    );
    if (!from || !target || from.id === target.id || dup) return;
    if (fromPort && toPort && !portCompatible(fromPort.type, toPort.type)) return;
    onChange(
      {
        ...graph,
        edges: [
          ...graph.edges,
          {
            id: `e${Date.now().toString(36)}${Math.floor(Math.random() * 1e4)}`,
            from_node: wire.fromNode,
            from_port: wire.fromPort,
            to_node: hotPort.node,
            to_port: hotPort.port,
          },
        ],
      },
      { checkpoint: true },
    );
  }

  function endGesture() {
    draggingRef.current = false;
    if (wire) {
      connectWire();
      setWire(null);
      setHotPort(null);
    }
    const pan = panRef.current;
    if (pan) {
      panRef.current = null;
      if (!pan.moved && pan.clear) {
        setSelection([]);
        onSelectNode(null);
        onSelectEdge(null);
      }
    }
    if (marquee) {
      const rect = rectFromPoints(marquee.x0, marquee.y0, marquee.x1, marquee.y1);
      const hits = graph.nodes
        .filter((n) => rectsIntersect(rect, { ...positions.get(n.id)!, w: NODE_W, h: NODE_H }))
        .map((n) => n.id);
      const ids = marquee.additive ? [...new Set([...selectionSet, ...hits])] : hits;
      setMarquee(null);
      if (rect.w > 4 || rect.h > 4) selectOnly(ids);
    }
    if (drag) {
      if (drag.moved && (drag.dx !== 0 || drag.dy !== 0)) {
        const ids = new Set(drag.ids);
        onChange(
          {
            ...graph,
            nodes: graph.nodes.map((n) => {
              if (!ids.has(n.id)) return n;
              const p = safePoint(n.position);
              return { ...n, position: { x: Math.round(p.x + drag.dx), y: Math.round(p.y + drag.dy) } };
            }),
          },
          { checkpoint: true },
        );
      } else if (!drag.moved) {
        if (drag.collapse) selectOnly([drag.origin]);
        // Clic sin arrastre: el panel que se abrió puede haber tapado el nodo.
        window.requestAnimationFrame(() => revealNode(drag.origin));
      }
      setDrag(null);
    }
  }

  // -- Rueda / trackpad ----------------------------------------------------------
  useEffect(() => {
    const el = hostRef.current;
    if (!el) return;
    const target = el;
    function onWheel(ev: WheelEvent) {
      if ((ev.target as HTMLElement).closest?.("[data-canvas-overlay]")) return;
      ev.preventDefault();
      const intent = wheelIntent(ev);
      if (intent.kind === "zoom") {
        const rect = target.getBoundingClientRect();
        const mx = ev.clientX - rect.left;
        const my = ev.clientY - rect.top;
        setView((v) => zoomAt(v, mx, my, v.s * intent.factor));
      } else {
        setView((v) => ({ ...v, x: v.x + intent.dx, y: v.y + intent.dy }));
      }
    }
    target.addEventListener("wheel", onWheel, { passive: false });
    return () => target.removeEventListener("wheel", onWheel);
  }, []);

  // -- Teclado -------------------------------------------------------------------
  const onKey = useStableHandler((ev: KeyboardEvent) => {
    const el = hostRef.current;
    if (!el) return;
    const active = document.activeElement;
    if (active && active !== document.body && !el.contains(active)) return;
    const t = ev.target as HTMLElement;
    if (isEditable(t) || t.closest?.("[data-canvas-overlay]")) return;
    const mod = ev.ctrlKey || ev.metaKey;
    if (ev.key === "Delete" || ev.key === "Backspace") {
      ev.preventDefault();
      deleteSelection();
    } else if (ev.key === "Escape") {
      if (menu) setMenu(null);
      else if (selectionSet.size || selectedEdgeId) selectOnly([]);
      else return;
      ev.preventDefault();
    } else if ((mod && ev.key.toLowerCase() === "f") || (!mod && ev.key === "/")) {
      ev.preventDefault();
      setSearchOpen(true);
    } else if (mod && ev.key.toLowerCase() === "a") {
      ev.preventDefault();
      selectOnly(graph.nodes.map((n) => n.id));
    } else if (mod && ev.key.toLowerCase() === "d") {
      ev.preventDefault();
      duplicateSelection();
    } else if (ev.shiftKey && !mod && ev.code === "Digit1") {
      ev.preventDefault();
      fitView();
    } else if (ev.shiftKey && !mod && ev.code === "Digit2") {
      ev.preventDefault();
      fitSelection();
    } else if (ev.shiftKey && !mod && ev.code === "Digit0") {
      ev.preventDefault();
      resetZoom();
    } else if (!mod && (ev.key === "+" || ev.key === "=" || ev.code === "NumpadAdd")) {
      ev.preventDefault();
      zoomBy(1.2);
    } else if (!mod && (ev.key === "-" || ev.code === "NumpadSubtract")) {
      ev.preventDefault();
      zoomBy(1 / 1.2);
    } else if (!mod && ev.key.startsWith("Arrow")) {
      ev.preventDefault();
      const step = ev.shiftKey ? NUDGE * 5 : NUDGE;
      const dx = ev.key === "ArrowLeft" ? -step : ev.key === "ArrowRight" ? step : 0;
      const dy = ev.key === "ArrowUp" ? -step : ev.key === "ArrowDown" ? step : 0;
      nudgeSelection(dx, dy);
    }
  });

  useEffect(() => {
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onKey]);

  // -- Handlers estables para los nodos (memo) --------------------------------------
  const onNodeDoubleClick = useStableHandler((id: string) => onNodeAction?.("configure", id));
  const onNodeContextMenu = useStableHandler((ev: ReactMouseEvent<HTMLDivElement>, id: string) => {
    ev.preventDefault();
    ev.stopPropagation();
    if (!selectionSet.has(id)) selectOnly([id]);
    const rect = hostRef.current!.getBoundingClientRect();
    setMenu({ x: ev.clientX - rect.left, y: ev.clientY - rect.top, nodeId: id, world: toWorld(ev.clientX, ev.clientY) });
  });
  const onNodeKeyDown = useStableHandler((ev: ReactKeyboardEvent<HTMLDivElement>, id: string) => {
    if (ev.key === "Enter" || ev.key === " ") {
      ev.preventDefault();
      if (!selectionSet.has(id) || selectionSet.size > 1) selectOnly([id]);
      else onSelectNode(id);
      if (ev.key === "Enter") onNodeAction?.("configure", id);
    } else if (ev.key === "ContextMenu" || (ev.shiftKey && ev.key === "F10")) {
      ev.preventDefault();
      const p = positions.get(id)!;
      setMenu({ x: view.x + (p.x + NODE_W / 2) * view.s, y: view.y + (p.y + NODE_H) * view.s, nodeId: id, world: p });
    }
  });
  const onNodeFocus = useStableHandler((id: string) => {
    const el = hostRef.current?.querySelector<HTMLElement>(`[data-node-id="${CSS.escape(id)}"]`);
    if (!el?.matches(":focus-visible")) return;
    const p = positions.get(id);
    if (p) setView((v) => revealRect(v, { x: p.x, y: p.y, w: NODE_W, h: NODE_H }, hostSize(), rightInset, 48));
  });

  const handlers: NodeHandlers = useMemo(
    () => ({
      onPointerDown: onNodePointerDown,
      onPortDown,
      onDoubleClick: onNodeDoubleClick,
      onContextMenu: onNodeContextMenu,
      onKeyDown: onNodeKeyDown,
      onFocus: onNodeFocus,
    }),
    [onNodePointerDown, onPortDown, onNodeDoubleClick, onNodeContextMenu, onNodeKeyDown, onNodeFocus],
  );

  const onSelectEdgeStable = useStableHandler((id: string) => {
    setSelection([]);
    onSelectNode(null);
    onSelectEdge(selectedEdgeId === id ? null : id);
  });

  function onBackgroundContextMenu(ev: ReactMouseEvent<HTMLDivElement>) {
    ev.preventDefault();
    const rect = hostRef.current!.getBoundingClientRect();
    setMenu({ x: ev.clientX - rect.left, y: ev.clientY - rect.top, nodeId: null, world: toWorld(ev.clientX, ev.clientY) });
  }

  // -- Drop desde el catálogo ------------------------------------------------------
  function onDragOver(ev: DragEvent<HTMLDivElement>) {
    if (!onDropNode || !ev.dataTransfer.types.includes(NODE_DND_TYPE)) return;
    ev.preventDefault();
    ev.dataTransfer.dropEffect = "copy";
    if (!dropActive) setDropActive(true);
  }

  function onDrop(ev: DragEvent<HTMLDivElement>) {
    setDropActive(false);
    const type = ev.dataTransfer.getData(NODE_DND_TYPE);
    if (!type || !onDropNode) return;
    ev.preventDefault();
    const w = toWorld(ev.clientX, ev.clientY);
    onDropNode(type, { x: Math.round(w.x - NODE_W / 2), y: Math.round(w.y - 24) });
  }

  // -- Render --------------------------------------------------------------------
  const lod = detailLevel(view.s);
  const visible = visibleWorldRect(view, host);
  const culled = graph.nodes.length > CULL_THRESHOLD;
  const cullRect = {
    x: visible.x - CULL_MARGIN,
    y: visible.y - CULL_MARGIN,
    w: visible.w + CULL_MARGIN * 2,
    h: visible.h + CULL_MARGIN * 2,
  };
  const renderedNodes = culled
    ? graph.nodes.filter(
        (n) => selectionSet.has(n.id) || rectsIntersect(cullRect, { ...positions.get(n.id)!, w: NODE_W, h: NODE_H }),
      )
    : graph.nodes;

  const bounds = useMemo(() => {
    let minX = 0;
    let minY = 0;
    let maxX = 800;
    let maxY = 500;
    for (const p of positions.values()) {
      minX = Math.min(minX, p.x);
      minY = Math.min(minY, p.y);
      maxX = Math.max(maxX, p.x + NODE_W);
      maxY = Math.max(maxY, p.y + NODE_H);
    }
    return { x: minX - 600, y: minY - 600, w: maxX - minX + 1200, h: maxY - minY + 1200 };
  }, [positions]);

  const failedIds = useMemo(
    () => new Set(Object.entries(overlay ?? {}).filter(([, r]) => r.status === "failed" || r.status === "denied").map(([id]) => id)),
    [overlay],
  );

  const wireStart = wire
    ? portPoint(nodesById.get(wire.fromNode), positions.get(wire.fromNode), wire.fromPort, "out", direction)
    : null;

  const menuItems: ContextMenuItem[] = menu
    ? menu.nodeId
      ? [
          { kind: "item", id: "configure", label: "Configurar", hint: "Enter", icon: <GearSix size={14} />, onSelect: () => onNodeAction?.("configure", menu.nodeId!) },
          { kind: "item", id: "run-node", label: "Probar este nodo", icon: <Play size={14} />, disabled: !onNodeAction, onSelect: () => onNodeAction?.("run_node", menu.nodeId!) },
          { kind: "item", id: "center", label: "Centrar en el lienzo", icon: <Crosshair size={14} />, onSelect: () => centerNode(menu.nodeId!) },
          { kind: "item", id: "duplicate", label: selectionSet.size > 1 ? `Duplicar ${selectionSet.size} nodos` : "Duplicar", hint: "Ctrl+D", icon: <Copy size={14} />, onSelect: duplicateSelection },
          { kind: "item", id: "fit-selection", label: "Encuadrar selección", hint: "Shift+2", icon: <SelectionAll size={14} />, onSelect: fitSelection },
          { kind: "separator", id: "sep" },
          { kind: "item", id: "delete", label: selectionSet.size > 1 ? `Eliminar ${selectionSet.size} nodos` : "Eliminar", hint: "Supr", icon: <Trash size={14} />, danger: true, onSelect: deleteSelection },
        ]
      : [
          { kind: "item", id: "add-here", label: "Añadir nodo aquí", icon: <Plus size={14} />, disabled: !onRequestAddNode, onSelect: () => onRequestAddNode?.(menu.world) },
          { kind: "item", id: "search", label: "Buscar nodo", hint: "Ctrl+F", icon: <MagnifyingGlass size={14} />, onSelect: () => setSearchOpen(true) },
          { kind: "item", id: "select-all", label: "Seleccionar todo", hint: "Ctrl+A", icon: <SelectionAll size={14} />, disabled: !graph.nodes.length, onSelect: () => selectOnly(graph.nodes.map((n) => n.id)) },
          { kind: "item", id: "fit-view", label: "Encuadrar todo", hint: "Shift+1", icon: <Crosshair size={14} />, disabled: !graph.nodes.length, onSelect: fitView },
          { kind: "separator", id: "sep" },
          { kind: "item", id: "layout-lr", label: "Ordenar en horizontal", icon: <TreeStructure size={14} />, disabled: !graph.nodes.length, onSelect: () => runAutoLayout("LR") },
          { kind: "item", id: "layout-tb", label: "Ordenar en vertical", icon: <TreeStructure size={14} className="rotate-90" />, disabled: !graph.nodes.length, onSelect: () => runAutoLayout("TB") },
        ]
    : [];

  const closeMenu = useCallback(() => setMenu(null), []);
  const closeSearch = useCallback(() => {
    setSearchOpen(false);
    hostRef.current?.focus({ preventScroll: true });
  }, []);
  const pickSearch = useStableHandler((id: string) => {
    setSearchOpen(false);
    selectOnly([id]);
    centerNode(id);
    window.requestAnimationFrame(() =>
      hostRef.current?.querySelector<HTMLElement>(`[data-node-id="${CSS.escape(id)}"]`)?.focus({ preventScroll: true }),
    );
  });
  const navigateMinimap = useStableHandler((wx: number, wy: number) => setView((v) => centerOn(v, wx, wy, hostSize())));

  return (
    <div
      ref={hostRef}
      data-testid="workflow-canvas"
      data-zoom={view.s.toFixed(3)}
      tabIndex={-1}
      aria-label="Lienzo del workflow"
      className={`relative w-full touch-none overflow-hidden bg-bg outline-none ${dropActive ? "ring-2 ring-accent/50 ring-inset" : ""} ${className}`}
      style={{
        backgroundImage:
          "radial-gradient(circle, color-mix(in srgb, var(--color-border) 70%, transparent) 1px, transparent 1px)",
        backgroundSize: `${22 * view.s}px ${22 * view.s}px`,
        backgroundPosition: `${view.x}px ${view.y}px`,
      }}
      onPointerDown={onHostPointerDown}
      onPointerMove={onPointerMove}
      onPointerUp={endGesture}
      onPointerCancel={endGesture}
      onContextMenu={onBackgroundContextMenu}
      onDragOver={onDragOver}
      onDragLeave={() => setDropActive(false)}
      onDrop={onDrop}
    >
      <div
        className="absolute top-0 left-0 will-change-transform"
        style={{ transform: `translate(${view.x}px, ${view.y}px) scale(${view.s})`, transformOrigin: "0 0" }}
      >
        <svg
          className="absolute overflow-visible"
          style={{ left: bounds.x, top: bounds.y }}
          width={bounds.w}
          height={bounds.h}
          aria-hidden
        >
          <g transform={`translate(${-bounds.x} ${-bounds.y})`}>
            <CanvasEdges
              edges={graph.edges}
              nodesById={nodesById}
              positions={positions}
              direction={direction}
              selectedEdgeId={selectedEdgeId}
              focusIds={selectionSet}
              overlay={overlay}
              onSelectEdge={onSelectEdgeStable}
            />
            {wire && wireStart && (
              <path
                d={wirePath(wireStart, { x: wire.x2, y: wire.y2 }, direction)}
                fill="none"
                stroke="var(--color-accent)"
                strokeWidth={2}
                strokeDasharray="5 4"
              />
            )}
          </g>
        </svg>

        {renderedNodes.map((n) => {
          const p = positions.get(n.id)!;
          const agentId = n.type === "llm" && n.config.agent_id ? String(n.config.agent_id) : null;
          return (
            <CanvasNode
              key={n.id}
              node={n}
              x={p.x}
              y={p.y}
              kind={canvasNodeKind(n, graph.metadata)}
              direction={direction}
              lod={lod}
              overviewScale={lod === "overview" ? view.s : 1}
              selected={selectionSet.has(n.id)}
              primary={selectedNodeId === n.id}
              run={overlay?.[n.id]}
              issue={nodeIssues?.[n.id]}
              agentName={agentId ? agentNames.get(agentId) : undefined}
              hotInPort={hotPort && hotPort.side === "in" && hotPort.node === n.id ? hotPort.port : null}
              wiringPort={wire && wire.fromNode === n.id ? wire.fromPort : null}
              handlers={handlers}
            />
          );
        })}

        {marquee && (
          <div
            className="pointer-events-none absolute rounded-sm border border-dashed border-accent bg-accent/10"
            data-testid="wf-marquee"
            style={(() => {
              const r = rectFromPoints(marquee.x0, marquee.y0, marquee.x1, marquee.y1);
              return { left: r.x, top: r.y, width: r.w, height: r.h };
            })()}
          />
        )}
      </div>

      {graph.nodes.length === 0 && (
        <div className="pointer-events-none absolute inset-0 flex items-center justify-center text-[13px] text-faint">
          Arrastra nodos desde el catálogo o pulsa “Añadir nodo”.
        </div>
      )}

      {searchOpen && (
        <div className="absolute top-3 left-1/2 z-30 flex w-full -translate-x-1/2 justify-center" data-canvas-overlay>
          <CanvasSearch graph={graph} onPick={pickSearch} onClose={closeSearch} />
        </div>
      )}

      {menu && (
        <div data-canvas-overlay>
          <CanvasContextMenu x={menu.x} y={menu.y} items={menuItems} onClose={closeMenu} bounds={host} />
        </div>
      )}

      {minimap && graph.nodes.length > 0 && (
        <div
          className="absolute bottom-3 z-20 overflow-hidden rounded-lg border border-border bg-raised/95 shadow-pop"
          style={{ right: 12 + rightInset }}
          data-canvas-overlay
        >
          <CanvasMinimap
            positions={positions}
            selected={selectionSet}
            failed={failedIds}
            visible={visible}
            onNavigate={navigateMinimap}
          />
        </div>
      )}

      {showToolbar && (
        <div
          className="pointer-events-none absolute bottom-3 z-20 flex justify-center"
          style={{ left: leftInset, right: rightInset }}
        >
          <div className="pointer-events-auto" data-canvas-overlay>
            <CanvasToolbar
              zoom={view.s}
              hasSelection={selectionSet.size > 0}
              minimap={minimap}
              onZoomIn={() => zoomBy(1.2)}
              onZoomOut={() => zoomBy(1 / 1.2)}
              onResetZoom={resetZoom}
              onFitView={fitView}
              onFitSelection={fitSelection}
              onSearch={() => setSearchOpen(true)}
              onLayout={runAutoLayout}
              onToggleMinimap={() => onToggleMinimap?.()}
              extra={toolbarExtra}
            />
          </div>
        </div>
      )}

      {selectionSet.size > 1 && (
        <div
          className="pointer-events-none absolute top-3 z-20 rounded-full border border-border bg-raised/95 px-3 py-1 text-[12px] text-muted shadow-pop"
          style={{ left: leftInset + 12 }}
          data-testid="wf-multi-selection"
          role="status"
        >
          {selectionSet.size} nodos seleccionados · arrastra para moverlos juntos
        </div>
      )}
    </div>
  );
}
