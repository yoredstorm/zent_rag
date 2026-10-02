import { describe, expect, it } from "vitest";
import { parseCognitiveStory } from "./cognitiveStory";

const STORY = {
  schema_version: 1,
  normal: [
    {
      kind: "cognitive_plan",
      phase: "planning",
      status: "ok",
      metrics: { complexity: "L3", needs: 2 },
    },
  ],
  expanded: { budget: { within_budget: true } },
  raw: { run_id: "run-1" },
};

describe("parseCognitiveStory", () => {
  it("parsea una story válida", () => {
    const story = parseCognitiveStory(STORY);
    expect(story?.normal).toHaveLength(1);
    expect(story?.normal[0].kind).toBe("cognitive_plan");
    expect(story?.raw.run_id).toBe("run-1");
  });

  it("devuelve null sin story o con shape inválido", () => {
    expect(parseCognitiveStory(undefined)).toBeNull();
    expect(parseCognitiveStory({ normal: "roto" })).toBeNull();
  });
});
