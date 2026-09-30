// =============================================================================
// Execution Story — render (§31, §53, §65)
// =============================================================================
// Verifica que la vista muestre la historia en lenguaje humano, que el modo
// técnico esté separado y que nunca se filtre razonamiento privado.
import { render, screen } from "@testing-library/react";
import { useState } from "react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import { buildExecutionStory } from "../executionStory";
import { ExecutionStoryView, type StoryMode } from "./ExecutionStoryView";

const COMPLEX_FLOW = {
  flow_version: 2,
  query_id: "q-9",
  status: "completed",
  verdict: { decider: "JEV", route: "Documentos" },
  decision: { evaluated: true, provider: "jev", confidence: 0.91, ms: 120 },
  generation: { model: "deepseek-v3.2", total_tokens: 1800, cost: 0.0004, ms: 900 },
  timings: { total_ms: 2400 },
  sources: [],
  fallbacks: [],
  events: [
    {
      id: "e-1",
      phase: "understanding",
      kind: "reasoning_classification",
      status: "ok",
      metrics: { reasoning: { shape: "STATE_TRANSITION", is_complex: true } },
    },
    {
      id: "e-2",
      phase: "context",
      kind: "company_context",
      status: "ok",
      metrics: { company_context: { concepts: 3, rules: 2, memories: 1 } },
    },
    {
      id: "e-3",
      phase: "reasoning",
      kind: "scenario_parse",
      status: "warn",
      metrics: {
        scenario: {
          events: 17,
          record_types: 2,
          schemas: 1,
          unparsed: 3,
          missing_requirements: [{ kind: "RECORD_LAYOUT_REQUIRED" }],
        },
      },
    },
    {
      id: "e-4",
      phase: "reasoning",
      kind: "state_reconstruction",
      status: "ok",
      metrics: {
        transitions: {
          total: 2,
          confirmed: 2,
          unresolved: 0,
          chain: [
            { from: "0005", to: "0006", status: "CONFIRMED" },
            { from: "0006", to: "0010", status: "CONFIRMED" },
          ],
        },
      },
    },
    {
      id: "e-5",
      phase: "reasoning",
      kind: "hypothesis_test",
      status: "ok",
      metrics: {
        hypotheses: {
          supported: 1,
          rejected: 1,
          unresolved: 0,
          items: [
            {
              id: "h-1",
              statement: "La renumeración abrió espacio",
              verdict: "SUPPORTED",
              origin: "RULE",
              supporting: 4,
              contradicting: 0,
            },
            {
              id: "h-2",
              statement: "Falta un registro de cierre",
              verdict: "REJECTED",
              origin: "USER",
              supporting: 0,
              contradicting: 3,
              is_user_hypothesis: true,
            },
          ],
        },
      },
    },
    {
      id: "e-6",
      phase: "verification",
      kind: "analysis_completion",
      status: "ok",
      metrics: { completion: { complete: true, blockers: [], reason_codes: [] } },
    },
    {
      id: "e-7",
      phase: "verification",
      kind: "fallback",
      status: "warn",
      summary: "grounding_failed",
    },
  ],
};

const HUMAN_NARRATIVE_FLOW = {
  flow_version: 2,
  status: "completed",
  timings: { total_ms: 27500 },
  generation: { cost: 0.00176 },
  events: [{ id: "final", phase: "generation", kind: "final", status: "ok" }],
  sources: [],
  execution_narrative: {
    schema_version: 1,
    outcome: {
      code: "ANSWERED_WITH_LIMITS",
      reason_code: "verification_partial",
      evidence_state: "complete",
      verification_state: "partial",
      final_status: "completed",
      answer_delivered: true,
    },
    summary: {
      decisions_influenced: 1,
      judgment_count: 4,
      jev_calls: 1,
      total_ms: 27500,
      cost_usd: 0.00176,
    },
    understanding: {
      application: "Aplicar la regla al fare basis de ejemplo",
      fields: ["FCLAS"],
      rules: ["&&&F"],
      examples: ["QNNF0SME"],
    },
    requirements: [
      { id: "f", label: "FCLAS", kind: "DOCUMENTABLE", status: "FOUND", source_required: true },
      { id: "r", label: "&&&F", kind: "DOCUMENTABLE", status: "FOUND", source_required: true },
      { id: "e", label: "QNNF0SME", kind: "USER_INPUT", status: "PROVIDED", source_required: false },
    ],
    journey: [
      { id: "j1", kind: "QUERY_UNDERSTOOD", sequence: 1 },
      { id: "j2", kind: "KNOWLEDGE_SEARCHED", sequence: 2 },
      { id: "j3", kind: "JEV_CHECKED", sequence: 3 },
      { id: "j4", kind: "SEARCH_RETRIED", sequence: 4, decision_id: "d1" },
      { id: "j5", kind: "EVIDENCE_COMPLETE", sequence: 5 },
      { id: "j6", kind: "LLM_ANALYZED", sequence: 6, call_id: "llm-1" },
      { id: "j7", kind: "ANSWER_DRAFTED", sequence: 7, call_id: "llm-2" },
      { id: "j8", kind: "ANSWER_VERIFIED", sequence: 8 },
    ],
    judgments: [
      { id: "needs_tool", question_code: "needs_tool", type: "NOUL", answer: "uncertain", certainty: 0.34, alternatives: [] },
      { id: "tool", question_code: "tool", type: "CHOICE", answer: "search_knowledge", probability: 0.79, certainty: 0.61, alternatives: [] },
      { id: "needs_more_evidence", question_code: "needs_more_evidence", type: "NOUL", answer: "yes", certainty: 0.55, confidence_band: "medium", applied_decision_id: "d1", alternatives: [] },
      { id: "satisfied", question_code: "satisfied", type: "NOUL", answer: "yes", certainty: 0.81, alternatives: [] },
    ],
    applied_decisions: [
      { id: "d1", phase: "post_retrieval", question_id: "needs_more_evidence", action: "retrieve_more", decider: "JEV", impact_code: "retrieve_more", affected_event_ids: [] },
    ],
    evidence: {
      complete: true,
      missing_documentable_evidence: [],
      conflicts: [],
      document_count: 2,
      passage_count: 5,
      searches: [{ index: 1, kind: "retrieval" }, { index: 2, kind: "jev_retrieval" }],
      documents: [
        { document_key: "document:rules", display_name: "Rec2_Rules.pdf", passage_count: 2, passages: [] },
        { document_key: "document:cat", display_name: "Rec2_Cat10.pdf", passage_count: 3, passages: [] },
      ],
    },
    model_calls: [
      { id: "llm-1", sequence: 1, purpose: "ANALYSIS", duration_ms: 7700 },
      { id: "llm-2", sequence: 2, purpose: "ANSWER", duration_ms: 5700 },
    ],
    verification: {
      overall: "partial",
      checks: [{ key: "grounding", state: "ok" }],
      fallback_used: true,
      fallback_code: "backup_verification",
      affected_outcome: false,
      corrections: [],
    },
    response_shape: {},
    learning: {},
    diagnostics: [],
  },
};

function renderStory(mode: StoryMode = "story") {
  const story = buildExecutionStory(COMPLEX_FLOW);
  const utils = render(
    <StoryHarness story={story} initialMode={mode} />,
  );
  return { story, ...utils };
}

/** El modo es controlado por el contenedor: el harness lo hace stateful. */
function StoryHarness({
  story,
  initialMode,
}: {
  story: ReturnType<typeof buildExecutionStory>;
  initialMode: StoryMode;
}) {
  const [mode, setMode] = useState<StoryMode>(initialMode);
  return (
    <ExecutionStoryView
      story={story}
      mode={mode}
      onModeChange={setMode}
      impact={{
        query_id: "q-9",
        truncated: false,
        counts: { used: 1, created: 1, reinforced: 0, contradicted: 0, validated: 0 },
        used: [],
        created: [],
        reinforced: [],
        contradicted: [],
        validated: [],
      }}
      impactState="ready"
      replay={null}
      replayError=""
      replayPending={false}
      onReplay={() => {}}
      showReplay
    />
  );
}

describe("ExecutionStoryView (§30, §31)", () => {
  it("mueve KNOWLEDGE REPRESENTATION fuera de Historia", async () => {
    const user = userEvent.setup();
    const story = buildExecutionStory({
      ...COMPLEX_FLOW,
      knowledge_representation: {
        document_understanding: "ACTIVE",
        canonical_version: "2",
        retrieval: "V1",
        source_profile_used: true,
        semantic_units: true,
        exact_literals: 3,
        legacy_chunks_used: true,
        warning: "DOCUMENT UNDERSTANDING ACTIVE BUT PRODUCTIVE RETRIEVAL IS V1",
      },
    });
    render(<StoryHarness story={story} initialMode="story" />);
    expect(screen.queryByLabelText("KNOWLEDGE REPRESENTATION")).toBeNull();
    await user.click(screen.getByRole("tab", { name: "Técnico" }));
    expect(screen.getByLabelText("KNOWLEDGE REPRESENTATION")).toBeTruthy();
    expect(screen.getAllByText("ACTIVE").length).toBeGreaterThan(0);
    expect(screen.getAllByText("DOCUMENT UNDERSTANDING ACTIVE BUT PRODUCTIVE RETRIEVAL IS V1").length).toBeGreaterThan(0);
  });

  it("muestra la historia en lenguaje humano con fases numeradas", () => {
    renderStory();
    expect(screen.getByText("Respuesta completada")).toBeTruthy();
    expect(screen.getAllByText(/reconstruyó el escenario/i).length).toBeGreaterThan(0);
    expect(screen.getByText("1. Entendió la pregunta")).toBeTruthy();
    expect(screen.getByText("2. Recuperó contexto empresarial")).toBeTruthy();
    expect(screen.getByText(/3\. Reconstruyó el escenario/)).toBeTruthy();
  });

  it("resume el contexto con conteos, no con telemetría", () => {
    renderStory();
    expect(screen.getAllByText(/3 conceptos/).length).toBeGreaterThan(0);
    expect(screen.getAllByText(/2 reglas/).length).toBeGreaterThan(0);
  });

  it("no muestra hipótesis ni timeline en una consulta simple", () => {
    const simple = buildExecutionStory({
      flow_version: 2,
      status: "completed",
      events: [
        {
          id: "s-1",
          phase: "understanding",
          kind: "reasoning_classification",
          status: "ok",
          metrics: { reasoning: { shape: "SIMPLE_LOOKUP" } },
        },
        { id: "s-2", phase: "generation", kind: "generation", status: "ok" },
      ],
      sources: [],
      fallbacks: [],
    });
    render(
      <ExecutionStoryView
        story={simple}
        mode="story"
        onModeChange={() => {}}
        impact={null}
        impactState="idle"
        replay={null}
        replayError=""
        replayPending={false}
        onReplay={() => {}}
      />,
    );
    expect(screen.queryByText(/Contrastó explicaciones/)).toBeNull();
    expect(screen.queryByText(/Reconstruyó el escenario/)).toBeNull();
  });

  it("separara la historia del detalle técnico", async () => {
    const user = userEvent.setup();
    renderStory();
    // La historia no expone la traza cruda.
    expect(screen.queryByText("Traza técnica")).toBeNull();
    await user.click(screen.getByRole("tab", { name: "Técnico" }));
    expect(screen.getAllByText("Traza técnica").length).toBeGreaterThan(0);
    expect(screen.getAllByText("deepseek-v3.2").length).toBeGreaterThan(0);
  });

  it("la pestaña Historia sigue siendo la vista principal", () => {
    renderStory();
    const storyTab = screen.getByRole("tab", { name: "Historia" });
    expect(storyTab.getAttribute("aria-selected")).toBe("true");
  });
});

describe("tres vistas (§37-§39, §62)", () => {
  it("ofrece Historia, Rendimiento y Técnico", () => {
    renderStory();
    expect(screen.getByRole("tab", { name: "Historia" })).toBeTruthy();
    expect(screen.getByRole("tab", { name: "Rendimiento" })).toBeTruthy();
    expect(screen.getByRole("tab", { name: "Técnico" })).toBeTruthy();
  });

  it("§62: la historia no muestra la matriz de observabilidad ni ids crudos", () => {
    renderStory();
    expect(screen.queryByText("Observabilidad")).toBeNull();
    expect(screen.queryByText("Trabajo acumulado (spans)")).toBeNull();
    expect(screen.queryByText(/Flow version/)).toBeNull();
  });

  it("§49: la matriz de observabilidad vive en Técnico, con estados explícitos", async () => {
    const user = userEvent.setup();
    renderStory();
    await user.click(screen.getByRole("tab", { name: "Técnico" }));
    expect(screen.getAllByText("Observabilidad").length).toBeGreaterThan(0);
    expect(screen.getAllByText(/Observado|No aplica|No disponible|No observado/).length).toBeGreaterThan(0);
  });

  it("§43: la vista de rendimiento explica el tiempo real de pared", async () => {
    const user = userEvent.setup();
    renderStory();
    await user.click(screen.getByRole("tab", { name: "Rendimiento" }));
    expect(screen.getByText(/Por qué demoró/)).toBeTruthy();
    expect(screen.getAllByText(/Llamadas al modelo/).length).toBeGreaterThan(0);
  });

  it("§50: la memoria se muestra una sola vez", () => {
    renderStory();
    expect(screen.getAllByText("Memoria").length).toBe(1);
  });
});

describe("Reasoning detail (§14-§22)", () => {
  it("muestra pregunta a demostrar, transiciones e hipótesis", () => {
    renderStory();
    expect(screen.getByText(/Análisis del escenario/)).toBeTruthy();
    expect(screen.getByText("La renumeración abrió espacio")).toBeTruthy();
    expect(screen.getByText("Falta un registro de cierre")).toBeTruthy();
    expect(screen.getByText("Respaldada")).toBeTruthy();
    expect(screen.getByText("Descartada")).toBeTruthy();
    expect(screen.getByText("tu hipótesis")).toBeTruthy();
  });

  it("declara el análisis completo sin depender del color", () => {
    renderStory();
    expect(screen.getAllByText(/ANÁLISIS COMPLETO/).length).toBeGreaterThan(0);
  });

  it("explica por qué no pudo interpretar todo el escenario", () => {
    renderStory();
    expect(screen.getAllByText(/no pudieron interpretarse/).length).toBeGreaterThan(0);
    expect(screen.getAllByText(/layout de los registros/).length).toBeGreaterThan(0);
  });
});

describe("ExecutionNarrative human-first", () => {
  it("cuenta una historia causal sin nombres internos ni JSON", () => {
    const story = buildExecutionStory(HUMAN_NARRATIVE_FLOW);
    render(<StoryHarness story={story} initialMode="story" />);

    expect(screen.getByText("Respuesta con verificación parcial")).toBeTruthy();
    expect(screen.getByText(/2 documentos · 5 fragmentos/)).toBeTruthy();
    expect(screen.getByText("Entendió tu consulta")).toBeTruthy();
    expect(screen.getByText("Qué necesitaba comprobar")).toBeTruthy();
    expect(screen.getAllByText("JEV revisó el camino").length).toBeGreaterThan(0);
    expect(screen.getByText(/4 comprobaciones/)).toBeTruthy();
    expect(screen.getByText(/1 influyó en la ejecución/)).toBeTruthy();
    expect(screen.getByText("El modelo resolvió el caso")).toBeTruthy();
    expect(screen.getByText(/2 llamadas al modelo/)).toBeTruthy();
    expect(screen.getByText("Verificación final")).toBeTruthy();
    expect(screen.queryByText("Evidencia insuficiente")).toBeNull();
    expect(screen.queryByText(/generation_package/i)).toBeNull();
    expect(screen.queryByText(/canonical_version/i)).toBeNull();
  });

  it("muestra preguntas observables de JEV e impacto aplicado", async () => {
    const user = userEvent.setup();
    const story = buildExecutionStory(HUMAN_NARRATIVE_FLOW);
    render(<StoryHarness story={story} initialMode="story" />);

    await user.click(screen.getByText("Ver las 4 comprobaciones"));
    expect(screen.getByText("¿Conviene buscar más evidencia?")).toBeTruthy();
    expect(screen.getAllByText("Certeza media").length).toBeGreaterThan(0);
    expect(screen.getByText(/Zent hizo una búsqueda adicional/)).toBeTruthy();
  });
});
