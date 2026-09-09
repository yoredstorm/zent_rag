import { Plus, Minus, Crosshair, Trash } from "@phosphor-icons/react";
import { useCallback, useEffect, useRef, useState } from "react";
import type { GraphEdge, GraphNode, WorkflowGraph } from "../lib/workflowGraph";
import { nodeMeta, portCompatible } from "../lib/workflowGraph";

export type RunOverlay = Record<
  string,
  { status: string; duration_ms?: number | null; error?: string | null; simulated?: boolean }
>;

const NODE_W = 232;
const NODE_H = 86;
const STATUS_CLS: Record<string, string> = {
  succeeded: "border-ok/70",
  simulated: "border-info/70",
  skipped: "border-faint/60 opacity-70",
  failed: "border-danger/80",
  denied: "border-danger/80",
  pending_approval: "border-warn/80",
  paused: "border-warn/60",
};

type Props = {
  graph: WorkflowGraph;
  onChange: (graph: WorkflowGraph) => void;
  selectedNodeId: string | null;
  onSelectNode: (id: string | null) => void;
  selectedEdgeId: string | null;
  onSelectEdge: (id: string | null) => void;
  overlay?: RunOverlay;
};

type Drag = { x: number; y: number; sx: number; sy: number };
type Wire = { fromNode: string; fromPort: string; x1: number; y1: number; x2: number; y2: number };

export function WorkflowCanvas({
  graph,
  onChange,
  selectedNodeId,
  onSelectNode,
  selectedEdgeId,
  onSelectEdge,
  overlay,
}: Props) {
  const hostRef = useRef<HTMLDivElement>(null);
  const [view, setView] = useState({ x: 60, y: 40, s: 1 });
  const [pan, setPan] = useState<Drag | null>(null);
  const [wire, setWire] = useState<Wire | null>(null);
  const [dragNode, setDragNode] = useState<{ id: string; dx: number; dy: number } | null>(null);
  const [hotPort, setHotPort] = useState<{ node: string; port: string; side: "in" | "out" } | null>(null);

  const toWorld = useCallback(
    (clientX: number, clientY: number) => {
      const rect = hostRef.current?.getBoundingClientRect();
      if (!rect) return { x: 0, y: 0 };
      return { x: (clientX - rect.left - view.x) / view.s, y: (clientY - rect.top - view.y) / view.s };
    },
    [view]
  );

  const nodeById = useCallback(
    (id: string) => graph.nodes.find((n) => n.id === id),
    [graph.nodes]
  );

  function edgePath(e: GraphEdge): string {
    const a = nodeById(e.from_node);
    const b = nodeById(e.to_node);
    if (!a || !b) return "";
    const fromIdx = Math.max(
      0,
      a.output_ports.findIndex((p) => p.name === e.from_port)
    );
    const toIdx = Math.max(0, b.input_ports.findIndex((p) => p.name === e.to_port));
    const x1 = a.position.x + NODE_W;
    const y1 = a.position.y + 26 + fromIdx * 22;
    const x2 = b.position.x;
    const y2 = b.position.y + 26 + toIdx * 22;
    const dx = Math.max(40, (x2 - x1) / 2);
    return `M ${x1} ${y1} C ${x1 + dx} ${y1}, ${x2 - dx} ${y2}, ${x2} ${y2}`;
  }

  function portPoint(nodeId: string, port: string, side: "in" | "out"): { x: number; y: number } {
    const n = nodeById(nodeId);
    if (!n) return { x: 0, y: 0 };
    const ports = side === "out" ? n.output_ports : n.input_ports;
    const idx = Math.max(0, ports.findIndex((p) => p.name === port));
    return {
      x: n.position.x + (side === "out" ? NODE_W : 0),
      y: n.position.y + 26 + idx * 22,
    };
  }

  // Zoom con rueda hacia el cursor; pan con drag del fondo.
  useEffect(() => {
    const el = hostRef.current;
    if (!el) return;
    const host = el;
    function onWheel(ev: WheelEvent) {
      ev.preventDefault();
      const rect = host.getBoundingClientRect();
      const mx = ev.clientX - rect.left;
      const my = ev.clientY - rect.top;
      setView((v) => {
        const s = Math.min(1.6, Math.max(0.45, v.s * (ev.deltaY < 0 ? 1.12 : 0.89)));
        return { x: mx - ((mx - v.x) / v.s) * s, y: my - ((my - v.y) / v.s) * s, s };
      });
    }
    el.addEventListener("wheel", onWheel, { passive: false });
    return () => el.removeEventListener("wheel", onWheel);
  }, []);

  function onBackgroundDown(ev: React.PointerEvent) {
    if (ev.button !== 0 || wire) return;
    onSelectNode(null);
    onSelectEdge(null);
    setPan({ x: ev.clientX, y: ev.clientY, sx: view.x, sy: view.y });
  }

  function onNodePointerDown(ev: React.PointerEvent, n: GraphNode) {
    if (ev.button !== 0 || wire) return;
    ev.stopPropagation();
    onSelectNode(n.id);
    onSelectEdge(null);
    setDragNode({ id: n.id, dx: ev.clientX, dy: ev.clientY });
  }

  function onPortDown(ev: React.PointerEvent, n: GraphNode, port: string, side: "in" | "out") {
    if (side !== "out") return;
    ev.stopPropagation();
    const p = portPoint(n.id, port, "out");
    setWire({ fromNode: n.id, fromPort: port, x1: p.x, y1: p.y, x2: p.x, y2: p.y });
    setHotPort({ node: n.id, port, side });
  }

  function onPointerMove(ev: React.PointerEvent) {
    if (wire) {
      const w = toWorld(ev.clientX, ev.clientY);
      setWire((cur) => (cur ? { ...cur, x2: w.x, y2: w.y } : cur));
      // hotspot bajo el cursor: leer name real del puerto (data-port-name)
      const el = document.elementFromPoint(ev.clientX, ev.clientY) as HTMLElement | null;
      const target = el?.closest<HTMLElement>("[data-port-name]");
      setHotPort(
        target
          ? {
              node: target.dataset.node!,
              port: target.dataset.portName ?? "in",
              side: (target.dataset.side as "in" | "out") ?? "in",
            }
          : null
      );
      return;
    }
    if (pan) {
      setView((v) => ({ ...v, x: pan.sx + (ev.clientX - pan.x), y: pan.sy + (ev.clientY - pan.y) }));
      return;
    }
    if (dragNode) {
      const w = toWorld(ev.clientX, ev.clientY);
      const start = mapRef.current?.get(dragNode.id);
      if (start) {
        onChange(
          withNodes(graph, (n) =>
            n.id === dragNode.id ? { ...n, position: { x: w.x - start.dx, y: w.y - start.dy } } : n
          )
        );
      }
    }
  }

  function endDrag() {
    if (wire && hotPort && hotPort.side === "in") {
      const from = nodeById(wire.fromNode);
      const target = nodeById(hotPort.node);
      const fromPort = from?.output_ports.find((p) => p.name === wire.fromPort);
      const toPort = target?.input_ports.find((p) => p.name === hotPort.port);
      const dup = graph.edges.some(
        (e) => e.from_node === wire.fromNode && e.from_port === wire.fromPort && e.to_node === hotPort.node
      );
      if (
        from &&
        target &&
        from.id !== target.id &&
        !dup &&
        (!fromPort || !toPort || portCompatible(fromPort.type, toPort.type))
      ) {
        onChange({
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
        });
      }
    }
    setWire(null);
    setHotPort(null);
    setPan(null);
    setDragNode(null);
  }

  function deleteSelected() {
    if (selectedNodeId) {
      const id = selectedNodeId;
      onChange({
        ...graph,
        nodes: graph.nodes.filter((n) => n.id !== id),
        edges: graph.edges.filter((e) => e.from_node !== id && e.to_node !== id),
        entrypoints: graph.entrypoints.filter((e) => e !== id),
      });
      onSelectNode(null);
    } else if (selectedEdgeId) {
      onChange({ ...graph, edges: graph.edges.filter((e) => e.id !== selectedEdgeId) });
      onSelectEdge(null);
    }
  }

  useEffect(() => {
    function onKey(ev: KeyboardEvent) {
      if (ev.key === "Delete" || ev.key === "Backspace") {
        const t = ev.target as HTMLElement;
        if (t && (t.tagName === "INPUT" || t.tagName === "TEXTAREA")) return;
        deleteSelected();
      }
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedNodeId, selectedEdgeId, graph]);

  const mapRef = useRef<Map<string, { dx: number; dy: number }>>(new Map());
  useEffect(() => {
    // Punto del nodo respecto al mouse en el nodo original
    mapRef.current.clear();
    for (const n of graph.nodes) mapRef.current.set(n.id, { dx: 0, dy: 0 });
  }, [graph.nodes.length]); // eslint-disable-line react-hooks/exhaustive-deps

  const bounds = {
    w: Math.max(800, ...graph.nodes.map((n) => n.position.x + NODE_W + 260)),
    h: Math.max(500, ...graph.nodes.map((n) => n.position.y + NODE_H + 200)),
  };

  const edgeExecuted = (e: GraphEdge) => {
    const s = overlay?.[e.from_node];
    return s && s.status !== "skipped" && s.status !== "failed" ? "stroke-ok/60" : "stroke-faint/40";
  };

  return (
    <div
      ref={hostRef}
      data-testid="workflow-canvas"
      className="relative h-[560px] w-full overflow-hidden rounded-md border border-border bg-soft/40"
      style={{
        backgroundImage: "radial-gradient(circle, var(--color-border) 1px, transparent 1px)",
        backgroundSize: "24px 24px",
      }}
      onPointerDown={onBackgroundDown}
      onPointerMove={onPointerMove}
      onPointerUp={endDrag}
      onPointerLeave={endDrag}
    >
      {/* Toolbar flotante */}
      <div className="absolute top-2 left-2 z-20 flex items-center gap-1 rounded-md border border-border bg-raised/95 p-1 shadow-pop">
        <button type="button" className="btn btn-ghost min-h-7 px-2" onClick={() => setView((v) => ({ ...v, s: Math.min(1.6, v.s * 1.2) }))} aria-label="Acercar">
          <Plus size={13} />
        </button>
        <button type="button" className="btn btn-ghost min-h-7 px-2" onClick={() => setView((v) => ({ ...v, s: Math.max(0.45, v.s / 1.2) }))} aria-label="Alejar">
          <Minus size={13} />
        </button>
        <button type="button" className="btn btn-ghost min-h-7 px-2" onClick={() => setView({ x: 60, y: 40, s: 1 })} aria-label="Centrar">
          <Crosshair size={13} />
          <span className="ml-1 text-[10px]">{Math.round(view.s * 100)}%</span>
        </button>
        {(selectedNodeId || selectedEdgeId) && (
          <button type="button" className="btn btn-ghost min-h-7 px-2 text-danger" onClick={deleteSelected} aria-label="Eliminar selección">
            <Trash size={13} />
          </button>
        )}
      </div>

      <div
        className="absolute top-0 left-0"
        style={{ transform: `translate(${view.x}px, ${view.y}px) scale(${view.s})`, transformOrigin: "0 0", width: bounds.w, height: bounds.h }}
      >
        <svg className="absolute top-0 left-0 overflow-visible" width={bounds.w} height={bounds.h}>
          {graph.edges.map((e) => {
            const selected = selectedEdgeId === e.id;
            const d = edgePath(e);
            return (
              <g key={e.id} className="cursor-pointer" onClick={(ev) => { ev.stopPropagation(); onSelectEdge(selected ? null : e.id); }}>
                <path d={d} fill="none" className={edgeExecuted(e)} strokeWidth={selected ? 3 : 2} strokeLinecap="round" />
                <path d={d} fill="none" className="stroke-transparent" strokeWidth={12} />
              </g>
            );
          })}
          {wire && (
            <path
              d={`M ${wire.x1} ${wire.y1} C ${wire.x1 + 60} ${wire.y1}, ${wire.x2 - 60} ${wire.y2}, ${wire.x2} ${wire.y2}`}
              fill="none"
              stroke="var(--color-accent)"
              strokeWidth={2}
              strokeDasharray="5 4"
            />
          )}
        </svg>

        {graph.nodes.map((n) => {
          const meta = nodeMeta(n.type);
          const run = overlay?.[n.id];
          const selected = selectedNodeId === n.id;
          const isHot = hotPort?.node === n.id;
          return (
            <div
              key={n.id}
              data-testid="wf-canvas-node"
              data-node-id={n.id}
              className={`absolute select-none rounded-md border bg-raised shadow-pop transition-colors ${
                selected ? "border-accent ring-1 ring-accent/40" : "border-border"
              } ${STATUS_CLS[run?.status ?? ""] ?? ""}`}
              style={{ left: n.position.x, top: n.position.y, width: NODE_W, cursor: "default" }}
              onPointerDown={(ev) => {
                const startW = toWorld(ev.clientX, ev.clientY);
                mapRef.current.set(n.id, { dx: n.position.x - startW.x, dy: n.position.y - startW.y });
                onNodePointerDown(ev, n);
              }}
            >
              <div className={`flex items-center gap-2 rounded-t-md px-2 py-1 text-[11px] font-semibold text-bg ${meta.color}`}>
                <span aria-hidden>{meta.icon}</span>
                <span className="flex-1 truncate">{meta.label}</span>
                {run && (
                  <span className={`badge ${run.status === "succeeded" ? "badge-ok" : run.status === "failed" ? "badge-danger" : run.status === "skipped" ? "badge-muted" : run.simulated ? "badge-info" : "badge-warning"}`}>
                    {run.status}
                  </span>
                )}
              </div>
              <div className="px-2 py-1">
                <p className="truncate text-[11px] text-muted">{meta.summary?.(n.config) ?? meta.label}</p>
                <p className="mt-0.5 flex items-center justify-between text-[9px] text-faint">
                  <span className="truncate">{n.id}</span>
                  {run?.duration_ms != null && <span>{run.duration_ms}ms</span>}
                </p>
              </div>
              {/* Puertos de entrada */}
              {n.input_ports.map((p, i) => (
                <span
                  key={`in-${p.name}`}
                  data-port data-node={n.id} data-port-name={p.name} data-side="in"
                  aria-label={`Entrada ${p.name}`}
                  className={`absolute top-0 h-3 w-3 -translate-x-1/2 rounded-full border-2 border-raised ${
                    isHot && hotPort?.side === "in" && hotPort?.port === p.name ? "bg-ok scale-125" : "bg-faint"
                  }`}
                  style={{ left: 0, top: 20 + i * 22 }}
                />
              ))}
              {/* Puertos de salida */}
              {n.output_ports.map((p, i) => (
                <span
                  key={`out-${p.name}`}
                  data-port data-node={n.id} data-port-name={p.name} data-side="out"
                  aria-label={`Conectar salida ${p.name}`}
                  title={p.name}
                  onPointerDown={(ev) => onPortDown(ev, n, p.name, "out")}
                  className={`absolute top-0 h-3 w-3 translate-x-1/2 cursor-crosshair rounded-full border-2 border-raised ${
                    wire && wire.fromNode === n.id && wire.fromPort === p.name ? "bg-accent shadow-glow" : "bg-accent/70 hover:bg-accent"
                  }`}
                  style={{ left: NODE_W, top: 20 + i * 22 }}
                />
              ))}
              {/* Labels de puertos condicionales */}
              {n.output_ports.length > 1 && (
                <span className="pointer-events-none absolute -right-1 translate-x-full text-[9px] text-faint" style={{ top: 20 + 1 * 22 }}>
                  {n.output_ports.map((p) => p.name).filter((x) => x !== "out").map((x) => (x === "then" ? "✓ sí" : "✗ no")).join(" / ")}
                </span>
              )}
            </div>
          );
        })}
      </div>

      {graph.nodes.length === 0 && (
        <div className="absolute inset-0 flex items-center justify-center text-xs text-faint">
          Arrastra nodos desde la biblioteca o usa “agregar nodo”.
        </div>
      )}
    </div>
  );
}

function withNodes(g: WorkflowGraph, fn: (n: GraphNode) => GraphNode): WorkflowGraph {
  return { ...g, nodes: g.nodes.map(fn) };
}