import { describe, expect, it } from "vitest";
import { BLOCK_REGISTRY } from "./workflowBlocks";
import { arrayToChain, blocksToIr, irToBlocks, makeBlock } from "./workflowIr";

describe("BLOCK_REGISTRY", () => {
  it("tiene hat, datos, if/else y notify", () => {
    const kinds = BLOCK_REGISTRY.map((b) => b.kind);
    expect(kinds).toEqual(
      expect.arrayContaining([
        "hat_schedule",
        "hat_webhook",
        "api_call",
        "kb_query",
        "llm",
        "condition",
        "notify",
      ])
    );
    expect(BLOCK_REGISTRY.find((b) => b.kind === "condition")?.hasThenElse).toBe(true);
  });
});

describe("workflowIr", () => {
  it("roundtrip schedule + api + si/si no + notify", () => {
    const hat = makeBlock("hat_schedule", { every_minutes: "5" });
    const api = makeBlock("api_call", {
      url: "https://stock.example.com/qty",
      method: "GET",
      json_path: "quantity",
    });
    const cond = makeBlock("condition", {
      field: "steps.0.output.extracted",
      operator: "<",
      value: "10",
    });
    cond.then = makeBlock("notify", { channel: "email", title: "Stock bajo", message: "bajo" });
    cond.else = makeBlock("notify", { channel: "in_app", title: "Stock OK", message: "ok" });
    hat.next = api;
    api.next = cond;

    const ir = blocksToIr(hat);
    expect(ir.trigger_type).toBe("schedule");
    expect(ir.trigger_config.every_minutes).toBe(5);
    expect(ir.steps).toHaveLength(2);
    expect(ir.steps[0].type).toBe("api_call");
    expect(ir.steps[1].type).toBe("condition");
    expect(ir.steps[1].then?.[0].type).toBe("notify");
    expect(ir.steps[1].else?.[0].config.channel).toBe("in_app");

    const back = irToBlocks(ir.trigger_type, ir.trigger_config, ir.steps);
    const ir2 = blocksToIr(back);
    expect(ir2.steps).toEqual(ir.steps);
    expect(ir2.trigger_type).toBe("schedule");
  });

  it("interpolación de reporters usa steps.N", () => {
    const chain = arrayToChain([
      { type: "api_call", config: { url: "https://x", json_path: "quantity" } },
      { type: "kb_query", config: { query: "{{steps.0.output.extracted}}" } },
    ]);
    expect(chain?.fields.url).toBe("https://x");
    expect(chain?.next?.fields.query).toContain("steps.0.output.extracted");
  });
});
