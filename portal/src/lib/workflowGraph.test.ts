import { describe, expect, it } from "vitest";
import {
  emptyGraph,
  layoutGraph,
  makeNode,
  portCompatible,
  prepareGraphForSave,
  referenceOptions,
  triggerConfigOf,
  triggerTypeOf,
} from "./workflowGraph";

describe("workflowGraph — IR del canvas", () => {
  it("emptyGraph crea un trigger + entrypoint válido", () => {
    const g = emptyGraph("webhook");
    expect(g.workflow_version).toBe(2);
    expect(g.nodes).toHaveLength(1);
    expect(g.nodes[0].type).toBe("trigger_webhook");
    expect(g.entrypoints).toEqual([g.nodes[0].id]);
  });

  it("triggerTypeOf / triggerConfigOf extraen schedule v2 sin cron manual", () => {
    const g = emptyGraph("schedule");
    g.nodes[0].config = { daily: "18:00", timezone: "America/Lima" };
    expect(triggerTypeOf(g)).toBe("schedule");
    const cfg = triggerConfigOf(g);
    expect(cfg.daily).toEqual({ time: "18:00" });
    expect(cfg.timezone).toBe("America/Lima");

    const gw = emptyGraph("webhook");
    expect(triggerTypeOf(gw)).toBe("webhook");
    expect(triggerConfigOf(gw)).toEqual({});
  });

  it("layoutGraph coloca nodos por niveles topológicos", () => {
    const g = emptyGraph("webhook");
    const b = makeNode("llm", { x: 0, y: 0 });
    b.id = "b";
    const c = makeNode("notify", { x: 0, y: 0 });
    c.id = "c";
    g.nodes.push(b, c);
    g.edges.push(
      { id: "e1", from_node: g.nodes[0].id, from_port: "out", to_node: "b", to_port: "in" },
      { id: "e2", from_node: "b", from_port: "out", to_node: "c", to_port: "in" }
    );
    layoutGraph(g);
    const t = g.nodes.find((n) => n.type === "trigger_webhook")!;
    const llm = g.nodes.find((n) => n.id === "b")!;
    const not = g.nodes.find((n) => n.id === "c")!;
    expect(llm.position.x).toBeGreaterThan(t.position.x);
    expect(not.position.x).toBeGreaterThan(llm.position.x);
    expect(not.position.y).toBe(llm.position.y);
  });

  it("prepareGraphForSave marca el subgrafo del for_each y fixea la versión", () => {
    const g = emptyGraph("webhook");
    const fe = makeNode("for_each", { x: 300, y: 0 });
    fe.id = "fe";
    const item = makeNode("notify", { x: 600, y: 0 });
    item.id = "item";
    const fin = makeNode("end", { x: 900, y: 0 });
    fin.id = "fin";
    g.nodes.push(fe, item, fin);
    g.edges.push(
      { id: "e1", from_node: g.nodes[0].id, from_port: "out", to_node: "fe", to_port: "in" },
      { id: "e2", from_node: "fe", from_port: "out", to_node: "item", to_port: "in" },
      { id: "e3", from_node: "fe", from_port: "done", to_node: "fin", to_port: "in" }
    );
    const saved = prepareGraphForSave(g);
    const feNode = saved.nodes.find((n) => n.id === "fe")!;
    expect(feNode.config._branch).toEqual(["item"]);
    expect(saved.workflow_version).toBe(2);
  });

  it("tipos de puerto validan compatibilidad", () => {
    expect(portCompatible("number", "number")).toBe(true);
    expect(portCompatible("number", "string")).toBe(true);
    expect(portCompatible("boolean", "number")).toBe(false);
    expect(portCompatible("record_list", "json")).toBe(true);
  });

  it("referenceOptions genera referencias estables por node id (sin índices)", () => {
    const g = emptyGraph("webhook");
    const llm = makeNode("llm", { x: 1, y: 1 });
    llm.id = "n_llm";
    llm.label = "Agente";
    g.nodes.push(llm);
    const refs = referenceOptions(g);
    expect(refs.some((r) => r.ref === "{{nodes.n_llm.output.text}}")).toBe(true);
    expect(refs.some((r) => r.ref.includes("steps."))).toBe(false);
    for (const r of refs) expect(r.ref).toMatch(/^\{\{nodes\.[A-Za-z0-9_-]+\./);
  });
});