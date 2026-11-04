import { act, createEvent, fireEvent, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { createRef, useState } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { saveViewport, viewportStorageKey } from "../lib/canvasViewport";
import { makeNode, type WorkflowGraph } from "../lib/workflowGraph";
import { WorkflowCanvas, type CanvasChangeOptions, type CanvasHandle } from "./WorkflowCanvas";
import { NODE_DND_TYPE } from "./workflowCanvas/geometry";

function fixture(): WorkflowGraph {
  const a = { ...makeNode("trigger_webhook", { x: 0, y: 0 }), id: "a", label: "Pedido recibido" };
  const b = { ...makeNode("condition", { x: 400, y: 0 }), id: "b", label: "¿Hay stock?" };
  const c = { ...makeNode("notify", { x: 800, y: 0 }), id: "c", label: "Avisar al cliente" };
  return {
    workflow_version: 2,
    nodes: [a, b, c],
    edges: [
      { id: "e1", from_node: "a", from_port: a.output_ports[0]?.name ?? "out", to_node: "b", to_port: "in" },
      { id: "e2", from_node: "b", from_port: b.output_ports[0]?.name ?? "out", to_node: "c", to_port: "in" },
    ],
    variables: {},
    entrypoints: ["a"],
    metadata: { canvas: true },
  };
}

type Change = { graph: WorkflowGraph; options?: CanvasChangeOptions };

function Harness({
  initial = fixture(),
  changes,
  handle,
  viewportKey,
  onDropNode,
  onNodeAction,
}: {
  initial?: WorkflowGraph;
  changes: Change[];
  handle?: React.Ref<CanvasHandle>;
  viewportKey?: string;
  onDropNode?: (type: string, world: { x: number; y: number }) => void;
  onNodeAction?: (action: string, id: string) => void;
}) {
  const [graph, setGraph] = useState(initial);
  const [selected, setSelected] = useState<string | null>(null);
  const [edge, setEdge] = useState<string | null>(null);
  return (
    <>
      <output data-testid="selected">{selected ?? ""}</output>
      <WorkflowCanvas
        ref={handle}
        graph={graph}
        onChange={(g, options) => {
          changes.push({ graph: g, options });
          setGraph(g);
        }}
        selectedNodeId={selected}
        onSelectNode={setSelected}
        selectedEdgeId={edge}
        onSelectEdge={setEdge}
        viewportKey={viewportKey}
        onDropNode={onDropNode}
        onNodeAction={onNodeAction}
      />
    </>
  );
}

const node = (id: string) => document.querySelector<HTMLElement>(`[data-node-id="${id}"]`)!;

function pointer(el: Element, type: "pointerDown" | "pointerMove" | "pointerUp", init: PointerEventInit = {}) {
  fireEvent[type](el, { button: 0, pointerId: 1, ...init });
}

describe("WorkflowCanvas", () => {
  it("arrastrar un nodo confirma la posición una sola vez, redondeada y como paso de historial", () => {
    const changes: Change[] = [];
    render(<Harness changes={changes} />);
    const host = screen.getByTestId("workflow-canvas");

    pointer(node("b"), "pointerDown", { clientX: 100, clientY: 100 });
    pointer(host, "pointerMove", { clientX: 130.4, clientY: 120 });
    pointer(host, "pointerMove", { clientX: 160.6, clientY: 150 });
    expect(changes).toHaveLength(0);
    pointer(host, "pointerUp", { clientX: 160.6, clientY: 150 });

    expect(changes).toHaveLength(1);
    expect(changes[0].options).toEqual({ checkpoint: true });
    const moved = changes[0].graph.nodes.find((n) => n.id === "b")!;
    expect(moved.position).toEqual({ x: 461, y: 50 });
    expect(changes[0].graph.edges).toEqual(fixture().edges);
    expect(screen.getByTestId("selected")).toHaveTextContent("b");
  });

  it("selección múltiple con Mayús: mueve el grupo junto y Supr borra ambos", () => {
    const changes: Change[] = [];
    render(<Harness changes={changes} />);
    const host = screen.getByTestId("workflow-canvas");

    pointer(node("a"), "pointerDown", { clientX: 10, clientY: 10 });
    pointer(host, "pointerUp", { clientX: 10, clientY: 10 });
    pointer(node("b"), "pointerDown", { clientX: 10, clientY: 10, shiftKey: true });
    pointer(host, "pointerUp", { clientX: 10, clientY: 10 });
    expect(screen.getByTestId("wf-multi-selection")).toHaveTextContent("2 nodos seleccionados");

    pointer(node("a"), "pointerDown", { clientX: 0, clientY: 0 });
    pointer(host, "pointerMove", { clientX: 20, clientY: 0 });
    pointer(host, "pointerUp", { clientX: 20, clientY: 0 });
    const positions = Object.fromEntries(changes[0].graph.nodes.map((n) => [n.id, n.position.x]));
    expect(positions).toEqual({ a: 20, b: 420, c: 800 });

    fireEvent.keyDown(document.body, { key: "Delete" });
    const last = changes.at(-1)!;
    expect(last.options).toEqual({ checkpoint: true });
    expect(last.graph.nodes.map((n) => n.id)).toEqual(["c"]);
    expect(last.graph.edges).toEqual([]);
    expect(last.graph.entrypoints).toEqual([]);
  });

  it("Ctrl+A y Ctrl+D duplican la selección con sus conexiones internas", () => {
    const changes: Change[] = [];
    render(<Harness changes={changes} />);
    fireEvent.keyDown(document.body, { key: "a", ctrlKey: true });
    expect(screen.getByTestId("wf-multi-selection")).toHaveTextContent("3 nodos");
    fireEvent.keyDown(document.body, { key: "d", ctrlKey: true });

    const g = changes.at(-1)!.graph;
    expect(g.nodes).toHaveLength(6);
    expect(g.edges).toHaveLength(4);
    const copies = g.nodes.slice(3);
    expect(copies.map((n) => n.position)).toEqual([
      { x: 40, y: 40 },
      { x: 440, y: 40 },
      { x: 840, y: 40 },
    ]);
    const copyIds = new Set(copies.map((n) => n.id));
    expect(g.edges.slice(2).every((e) => copyIds.has(e.from_node) && copyIds.has(e.to_node))).toBe(true);
  });

  it("Esc limpia la selección y no consume la tecla si no hay nada que limpiar", () => {
    const changes: Change[] = [];
    render(<Harness changes={changes} />);
    pointer(node("a"), "pointerDown");
    pointer(screen.getByTestId("workflow-canvas"), "pointerUp");
    expect(screen.getByTestId("selected")).toHaveTextContent("a");

    const first = createEvent.keyDown(document.body, { key: "Escape" });
    fireEvent(document.body, first);
    expect(first.defaultPrevented).toBe(true);
    expect(screen.getByTestId("selected")).toHaveTextContent("");

    const second = createEvent.keyDown(document.body, { key: "Escape" });
    fireEvent(document.body, second);
    expect(second.defaultPrevented).toBe(false);
  });

  it("el handle controla el zoom sin tocar el grafo", () => {
    const changes: Change[] = [];
    const handle = createRef<CanvasHandle>();
    render(<Harness changes={changes} handle={handle} />);
    const host = screen.getByTestId("workflow-canvas");
    expect(host).toHaveAttribute("data-zoom", "1.000");

    act(() => handle.current!.zoomBy(1.5));
    expect(host).toHaveAttribute("data-zoom", "1.500");
    expect(screen.getByTestId("wf-zoom-level")).toHaveTextContent("150%");

    fireEvent.click(screen.getByTestId("wf-zoom-level"));
    expect(host).toHaveAttribute("data-zoom", "1.000");

    act(() => handle.current!.setViewport({ x: 0, y: 0, s: 9 }));
    expect(handle.current!.getViewport().s).toBe(2);
    expect(changes).toHaveLength(0);
  });

  it("ordenar en vertical cambia posiciones y dirección, conserva relaciones y es un paso deshacible", async () => {
    const changes: Change[] = [];
    const user = userEvent.setup();
    render(<Harness changes={changes} />);
    await user.click(screen.getByTestId("wf-autolayout"));
    await user.click(await screen.findByTestId("wf-autolayout-tb"));

    expect(changes).toHaveLength(1);
    const { graph, options } = changes[0];
    expect(options).toEqual({ checkpoint: true });
    expect(graph.metadata.canvas_direction).toBe("TB");
    expect(graph.edges).toEqual(fixture().edges);
    const ys = graph.nodes.map((n) => n.position.y);
    expect(ys[0]).toBeLessThan(ys[1]);
    expect(ys[1]).toBeLessThan(ys[2]);
  });

  it("menú contextual del nodo: configurar y eliminar", async () => {
    const changes: Change[] = [];
    const onNodeAction = vi.fn();
    const user = userEvent.setup();
    render(<Harness changes={changes} onNodeAction={onNodeAction} />);

    fireEvent.contextMenu(node("b"), { clientX: 50, clientY: 50 });
    expect(screen.getByTestId("wf-canvas-menu")).toBeInTheDocument();
    await user.click(screen.getByTestId("wf-menu-configure"));
    expect(onNodeAction).toHaveBeenCalledWith("configure", "b");

    fireEvent.contextMenu(node("b"), { clientX: 50, clientY: 50 });
    await user.click(screen.getByTestId("wf-menu-delete"));
    expect(changes.at(-1)!.graph.nodes.map((n) => n.id)).toEqual(["a", "c"]);
  });

  it("Ctrl+F busca por nombre y Enter selecciona el nodo", async () => {
    const changes: Change[] = [];
    const user = userEvent.setup();
    render(<Harness changes={changes} />);
    fireEvent.keyDown(document.body, { key: "f", ctrlKey: true });
    const input = await screen.findByTestId("wf-canvas-search-input");
    await user.type(input, "stock");
    expect(screen.getAllByTestId("wf-canvas-search-hit")).toHaveLength(1);
    await user.keyboard("{Enter}");
    expect(screen.queryByTestId("wf-canvas-search")).not.toBeInTheDocument();
    expect(screen.getByTestId("selected")).toHaveTextContent("b");
    expect(changes).toHaveLength(0);
  });

  it("Enter sobre un nodo enfocado abre su configuración", () => {
    const onNodeAction = vi.fn();
    render(<Harness changes={[]} onNodeAction={onNodeAction} />);
    fireEvent.keyDown(node("c"), { key: "Enter" });
    expect(screen.getByTestId("selected")).toHaveTextContent("c");
    expect(onNodeAction).toHaveBeenCalledWith("configure", "c");
  });

  it("soltar un nodo del catálogo informa tipo y punto de mundo", () => {
    const onDropNode = vi.fn();
    render(<Harness changes={[]} onDropNode={onDropNode} />);
    const host = screen.getByTestId("workflow-canvas");
    const dataTransfer = {
      types: [NODE_DND_TYPE],
      getData: (t: string) => (t === NODE_DND_TYPE ? "notify" : ""),
      dropEffect: "none",
    };
    fireEvent.dragOver(host, { dataTransfer });
    const drop = createEvent.drop(host, { dataTransfer });
    Object.defineProperties(drop, { clientX: { value: 600 }, clientY: { value: 300 } });
    fireEvent(host, drop);
    expect(onDropNode).toHaveBeenCalledWith("notify", { x: 600 - 60 - 124, y: 300 - 40 - 24 });
  });
});

describe("WorkflowCanvas · viewport persistido", () => {
  beforeEach(() => {
    vi.spyOn(HTMLElement.prototype, "clientWidth", "get").mockReturnValue(1200);
    vi.spyOn(HTMLElement.prototype, "clientHeight", "get").mockReturnValue(700);
  });
  afterEach(() => vi.useRealTimers());

  it("restaura el viewport guardado del usuario en vez de reencuadrar", () => {
    const key = viewportStorageKey("u1", "wf1");
    saveViewport(key, { x: -120, y: 30, s: 0.65 });
    render(<Harness changes={[]} viewportKey={key} />);
    expect(screen.getByTestId("workflow-canvas")).toHaveAttribute("data-zoom", "0.650");
  });

  it("guarda el viewport tras navegar y no reencuadra al seleccionar", () => {
    vi.useFakeTimers();
    const handle = createRef<CanvasHandle>();
    const key = viewportStorageKey("u1", "wf2");
    render(<Harness changes={[]} handle={handle} viewportKey={key} />);
    act(() => handle.current!.setViewport({ x: 10, y: 20, s: 1.3 }));
    act(() => vi.advanceTimersByTime(300));
    const stored = JSON.parse(window.localStorage.getItem(key) ?? "null");
    expect(stored).toMatchObject({ s: 1.3 });

    pointer(node("a"), "pointerDown");
    pointer(screen.getByTestId("workflow-canvas"), "pointerUp");
    expect(handle.current!.getViewport().s).toBe(1.3);
  });
});
