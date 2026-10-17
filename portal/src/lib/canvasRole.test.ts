import { describe, expect, it } from "vitest";
import { CANVAS_ROLE_META, resolveCanvasRole } from "./canvasRole";

describe("resolveCanvasRole", () => {
  it("respeta metadata.canvas_role del nodo", () => {
    expect(
      resolveCanvasRole({
        type: "capability_call",
        config: { capability: "sales.order.create" },
        metadata: { canvas_role: "payment" },
      })
    ).toBe("payment");
  });

  it("usa graph.metadata.canvas.roles cuando el nodo no trae rol", () => {
    expect(
      resolveCanvasRole(
        { id: "n1", type: "capability_call", config: {} },
        { canvas: { roles: { n1: "data" } } }
      )
    ).toBe("data");
  });

  it("deriva del tipo y la capacidad cuando falta el rol", () => {
    expect(
      resolveCanvasRole({ type: "capability_call", config: { capability: "catalog.products.search" } })
    ).toBe("data");
    expect(
      resolveCanvasRole({ type: "capability_call", config: { capability: "inventory.stock.get" } })
    ).toBe("data");
    expect(
      resolveCanvasRole({ type: "capability_call", config: { capability: "sales.order.create" } })
    ).toBe("action");
    expect(
      resolveCanvasRole({ type: "capability_call", config: { capability: "payments.checkout.create" } })
    ).toBe("payment");
    expect(resolveCanvasRole({ type: "wait_event", config: { preset: "payment" } })).toBe("payment");
    expect(resolveCanvasRole({ type: "wait_event", config: {} })).toBe("wait");
    expect(resolveCanvasRole({ type: "human_approval" })).toBe("wait");
    expect(resolveCanvasRole({ type: "trigger_event" })).toBe("trigger");
    expect(resolveCanvasRole({ type: "llm" })).toBe("ai");
    expect(resolveCanvasRole({ type: "condition" })).toBe("decision");
    expect(resolveCanvasRole({ type: "business_result" })).toBe("business_result");
    expect(resolveCanvasRole({ type: "end" })).toBe("end");
    expect(resolveCanvasRole({ type: "state_set" })).toBe("data");
    expect(resolveCanvasRole({ type: "notify" })).toBe("action");
  });

  it("espera se distingue de acción y pago (icono propio)", () => {
    expect(CANVAS_ROLE_META.wait.icon).not.toBe(CANVAS_ROLE_META.action.icon);
    expect(CANVAS_ROLE_META.wait.icon).not.toBe(CANVAS_ROLE_META.payment.icon);
    expect(CANVAS_ROLE_META.action.icon).not.toBe(CANVAS_ROLE_META.payment.icon);
  });
});
