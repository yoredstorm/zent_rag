import { describe, expect, it } from "vitest";
import { autoLayout, countEdgeCrossings, countNodeOverlaps, graphDirection } from "./graphAutoLayout";
import { NODE_H, NODE_W } from "./canvasViewport";
import { makeNode, type GraphEdge, type WorkflowGraph } from "./workflowGraph";

function graphOf(types: [string, string][], links: [string, string, string?][]): WorkflowGraph {
  const nodes = types.map(([id, type]) => ({ ...makeNode(type, { x: 0, y: 0 }), id }));
  const edges: GraphEdge[] = links.map(([from, to, port], i) => ({
    id: `e${i}`,
    from_node: from,
    from_port: port ?? "out",
    to_node: to,
    to_port: "in",
  }));
  return { workflow_version: 2, nodes, edges, variables: {}, entrypoints: [nodes[0].id], metadata: {} };
}

/** Rombo con ramas cruzadas a propósito en las posiciones iniciales. */
function tangled(): WorkflowGraph {
  const g = graphOf(
    [
      ["t", "trigger_webhook"],
      ["c", "condition"],
      ["a", "notify"],
      ["b", "notify"],
      ["a2", "set_variable"],
      ["b2", "set_variable"],
      ["end", "end"],
    ],
    [
      ["t", "c"],
      ["c", "a", "then"],
      ["c", "b", "else"],
      ["a", "a2"],
      ["b", "b2"],
      ["a2", "end"],
      ["b2", "end"],
    ],
  );
  const pos: Record<string, [number, number]> = {
    t: [0, 200],
    c: [300, 200],
    a: [600, 400],
    b: [600, 0],
    a2: [900, 0],
    b2: [900, 400],
    end: [1200, 200],
  };
  g.nodes.forEach((n) => (n.position = { x: pos[n.id][0], y: pos[n.id][1] }));
  return g;
}

describe("autoLayout", () => {
  it("asigna capas por dependencia en horizontal sin solapes", () => {
    const g = tangled();
    const { graph, layers } = autoLayout(g, "LR");
    expect(layers[0]).toEqual(["t"]);
    expect(layers[1]).toEqual(["c"]);
    expect(layers.at(-1)).toEqual(["end"]);
    const x = (id: string) => graph.nodes.find((n) => n.id === id)!.position.x;
    expect(x("t")).toBeLessThan(x("c"));
    expect(x("c")).toBeLessThan(x("a"));
    expect(x("a2")).toBeLessThan(x("end"));
    expect(countNodeOverlaps(graph)).toBe(0);
  });

  it("reduce cruces respecto de un layout enredado", () => {
    const g = tangled();
    const before = countEdgeCrossings(g, "LR");
    const after = countEdgeCrossings(autoLayout(g, "LR").graph, "LR");
    expect(before).toBeGreaterThan(0);
    expect(after).toBeLessThan(before);
    expect(after).toBe(0);
  });

  it("no altera aristas, puertos ni configuración", () => {
    const g = tangled();
    g.nodes[1].config = { field: "{{trigger.x}}", operator: ">", value: "1" };
    const { graph } = autoLayout(g, "TB");
    expect(graph.edges).toEqual(g.edges);
    expect(graph.nodes.map((n) => [n.id, n.type, n.config, n.input_ports, n.output_ports])).toEqual(
      g.nodes.map((n) => [n.id, n.type, n.config, n.input_ports, n.output_ports]),
    );
    expect(graph.entrypoints).toEqual(g.entrypoints);
  });

  it("vertical apila capas en Y y guarda la orientación", () => {
    const { graph } = autoLayout(tangled(), "TB");
    const y = (id: string) => graph.nodes.find((n) => n.id === id)!.position.y;
    expect(y("t")).toBeLessThan(y("c"));
    expect(y("c")).toBeLessThan(y("a"));
    expect(graphDirection(graph)).toBe("TB");
    expect(countNodeOverlaps(graph)).toBe(0);
  });

  it("tolera ciclos (loop de reintento) y nodos sueltos", () => {
    const g = graphOf(
      [
        ["t", "trigger_webhook"],
        ["ask", "llm"],
        ["check", "condition"],
        ["loose", "notify"],
      ],
      [
        ["t", "ask"],
        ["ask", "check"],
        ["check", "ask", "else"],
      ],
    );
    const { graph } = autoLayout(g, "LR");
    expect(countNodeOverlaps(graph)).toBe(0);
    const loose = graph.nodes.find((n) => n.id === "loose")!;
    const others = graph.nodes.filter((n) => n.id !== "loose");
    expect(loose.position.y).toBeGreaterThanOrEqual(Math.max(...others.map((n) => n.position.y)) + NODE_H);
  });

  it("es determinista y conserva el origen del grafo", () => {
    const g = tangled();
    const a = autoLayout(g, "LR").graph;
    const b = autoLayout(structuredClone(g), "LR").graph;
    expect(a.nodes.map((n) => n.position)).toEqual(b.nodes.map((n) => n.position));
    expect(Math.min(...a.nodes.map((n) => n.position.x))).toBe(0);
    expect(Math.min(...a.nodes.map((n) => n.position.y))).toBe(0);
    expect(NODE_W).toBeGreaterThan(0);
  });
});
