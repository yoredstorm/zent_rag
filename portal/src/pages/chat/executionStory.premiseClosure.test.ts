// =============================================================================
// Mapeo de la cadena determinista en la historia de ejecución
// =============================================================================
// Los steps nuevos (rule_retrieval, requirement_graph, premise_closure,
// decision_envelope, ...) NO pueden desaparecer ni contarse como no mapeados.
// Un tipo desconocido se muestra en la sección técnica con unmapped=true.
// =============================================================================
import { describe, expect, it } from "vitest";

import { buildExecutionStory, kindTitle } from "./executionStory";

const DETERMINISTIC_STEPS = [
  { type: "query_semantics", status: "ok", intent: "VALIDATE" },
  { type: "rule_retrieval", status: "ok", strategy: "canonical_first", candidates_found: 3, supported_rules: 1 },
  { type: "rule_evaluation", status: "warn", executable_rules: 1, missing_requirements: ["length_policy"] },
  { type: "requirement_graph", status: "warn", missing_premises: ["definition:symbol:&", "length_policy"] },
  {
    type: "premise_closure",
    status: "ok",
    termination: "SATISFIED",
    rounds: 2,
    information_gain: 2,
    missing_before: ["definition:symbol:&", "length_policy"],
    missing_after: [],
  },
  { type: "grounding", status: "ok", answerability: "ANSWERABLE_DERIVED" },
  { type: "decision_envelope", status: "ok", operation: "POSITIONAL_MATCH", result: "MATCH", authoritative: true },
  { type: "derived_claim", status: "ok", operation: "POSITIONAL_MATCH", deterministic: true },
  { type: "answer_state", status: "ok", state: "DERIVED_RESULT" },
  { type: "derived_guard", status: "ok", action: "override" },
  { type: "finalization", status: "ok" },
  { type: "build", status: "ok", git_sha: "abc123", git_sha_display: "abc123" },
];

describe("cadena determinista mapeada", () => {
  it("no desaparece ningún step nuevo ni se marca unmapped", () => {
    const story = buildExecutionStory({ steps: DETERMINISTIC_STEPS });
    expect(story.counts.unmapped).toBe(0);
    const kinds = story.phases.flatMap((phase) => phase.events).map((event) => event.kind);
    for (const step of DETERMINISTIC_STEPS) {
      expect(kinds).toContain(step.type);
    }
    const closure = story.phases
      .flatMap((phase) => phase.events)
      .find((event) => event.kind === "premise_closure");
    expect(closure?.metrics.termination).toBe("SATISFIED");
  });

  it("los títulos son humanos, no el type crudo", () => {
    for (const step of DETERMINISTIC_STEPS) {
      expect(kindTitle(step.type)).not.toBe(step.type);
    }
  });

  it("un tipo desconocido se muestra como no mapeado, no se pierde", () => {
    const story = buildExecutionStory({
      steps: [...DETERMINISTIC_STEPS, { type: "paso_futuro", status: "ok", foo: "bar" }],
    });
    expect(story.counts.unmapped).toBe(1);
    const unknown = story.phases
      .flatMap((phase) => phase.events)
      .find((event) => event.kind === "paso_futuro");
    expect(unknown).toBeDefined();
    expect(unknown?.technical?.unmapped).toBe(true);
  });
});
