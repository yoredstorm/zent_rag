// =============================================================================
// Vista explicada — "Cómo llegó Zent a esta respuesta" con el contrato canónico
// =============================================================================
// Verifica la separación EJECUCIÓN / EVIDENCIA / DECISIONES / VERIFICACIÓN,
// que la evidencia se agrupe por documento y que nada se invente sin telemetría.
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import { buildExecutionStory } from "../executionStory";
import { parseTraceability } from "../experience";
import { ExperienceStory } from "./ExperienceStory";
import { ExecutionStoryView } from "./ExecutionStoryView";

const TRACEABILITY = {
  schema_version: 1,
  counts: {
    documents_consulted: 3,
    documents_used: 2,
    evidence_retrieved: 5,
    evidence_used: 4,
    evidence_cited: 1,
  },
  evidence: {
    documents: [
      {
        document_key: "document:docA",
        document_id: "docA",
        document_name: "Rec2_Rules_dapp_C.pdf",
        evidence_count: 2,
        used_count: 2,
        items: [
          {
            evidence_id: "E1",
            document_id: "docA",
            document_name: "Rec2_Rules_dapp_C.pdf",
            page: 18,
            section_path: ["Record 2"],
            excerpt: "Carrier Code ...",
            status: "USED",
            used_in_answer: true,
            cited: true,
          },
          {
            evidence_id: "E2",
            document_name: "Rec2_Rules_dapp_C.pdf",
            page: 7,
            excerpt: "Segundo fragmento del mismo documento.",
            status: "USED",
            used_in_answer: true,
          },
        ],
      },
      {
        document_key: "document:docB",
        document_id: "docB",
        document_name: "Cat10_dapp_C.pdf",
        evidence_count: 2,
        used_count: 2,
        items: [
          {
            evidence_id: "E3",
            document_name: "Cat10_dapp_C.pdf",
            page: 11,
            excerpt: "Contenido de categoría.",
            status: "USED",
            used_in_answer: true,
          },
          {
            evidence_id: "E4",
            document_name: "Cat10_dapp_C.pdf",
            status: "USED",
            used_in_answer: true,
          },
        ],
      },
      {
        document_key: "document:docC",
        document_id: "docC",
        document_name: "",
        evidence_count: 1,
        used_count: 0,
        items: [{ evidence_id: "E5", status: "RETRIEVED", used_in_answer: false }],
      },
    ],
    items: [],
  },
  retrieval: { rounds: [], expanded: true },
  decisions: [
    {
      decision_id: "decision:1:pre_generation",
      phase: "pre_generation",
      action: "retrieve_more",
      action_applied: true,
      classification: "ACTIONABLE",
      effect_codes: ["retrieval_round_requested"],
      reason_codes: ["unsatisfied_answerable_from_current_evidence"],
      display: { outcome_key: "retrieve_more", probability: 0.87, confidence_band: "high" },
      before_state: { evidence: 3, sufficient: false },
      after_state: { evidence: 5, sufficient: true },
      delta_evidence: 2,
    },
    {
      decision_id: "decision:2:pre_reasoning",
      phase: "pre_reasoning",
      action: "generate",
      action_applied: false,
      classification: "OBSERVATIONAL",
      display: { outcome_key: "generate" },
    },
  ],
  judgments: [],
  timeline: [
    {
      id: "trace:1",
      type: "QUERY_CLASSIFIED",
      sequence: 1,
      summary_code: "understood.query",
      summary_params: {},
      user_visible: true,
      status: "ok",
    },
    {
      id: "trace:2",
      type: "RETRIEVAL_COMPLETED",
      sequence: 2,
      summary_code: "retrieval.completed",
      summary_params: { chunks: 5, evidence_used: 4, documents_used: 2 },
      user_visible: true,
      status: "ok",
    },
    {
      id: "trace:3",
      type: "RETRIEVAL_EXPANDED",
      sequence: 3,
      summary_code: "retrieval.expanded",
      summary_params: { before: 3, after: 5, delta: 2 },
      user_visible: true,
      status: "ok",
      decision_id: "decision:1:pre_generation",
    },
    {
      id: "trace:4",
      type: "RESPONSE_DELIVERED",
      sequence: 4,
      summary_code: "response.delivered",
      summary_params: {},
      user_visible: true,
      status: "ok",
    },
  ],
  verification: {
    status: "PARTIALLY_VERIFIED",
    explanation_codes: [
      { code: "DOCUMENTARY_SUPPORT_CONFIRMED" },
      { code: "SECONDARY_CHECK_UNAVAILABLE", check: "answer_gate" },
    ],
    checks: [{ key: "grounding", state: "ok" }],
    signals: { grounded: true, fallback_used: false, material_fallback: false },
    technical: {},
  },
  diagnostics: { invariants: [], gaps: [] },
};

const FLOW = {
  flow_version: 2,
  status: "completed",
  timings: { total_ms: 25600 },
  generation: { cost: 0.001124, model: "m" },
  events: [{ id: "final", phase: "generation", kind: "final", status: "ok" }],
  sources: [],
  fallbacks: [],
  traceability: TRACEABILITY,
};

function renderExplained() {
  const story = buildExecutionStory(FLOW);
  return render(
    <ExecutionStoryView
      story={story}
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
}

describe("ExperienceStory — vista explicada", () => {
  it("muestra la cabecera con conteos reales de documento y evidencia", () => {
    renderExplained();
    expect(screen.getByText("Respuesta respaldada parcialmente")).toBeTruthy();
    expect(screen.getByText("2 documentos · 4 evidencias")).toBeTruthy();
    expect(screen.getByText("1 intervención")).toBeTruthy();
    expect(screen.getByText(/25\.6 s/)).toBeTruthy();
    expect(screen.getByText(/0\.001124/)).toBeTruthy();
  });

  it("narra la ejecución con eventos reales y sin pasos genéricos", () => {
    renderExplained();
    expect(screen.getByText("Cómo llegó Zent a esta respuesta")).toBeTruthy();
    expect(screen.getByText("Entendió la consulta")).toBeTruthy();
    expect(screen.getByText("Buscó evidencia")).toBeTruthy();
    expect(screen.getByText("JEV pidió ampliar la búsqueda")).toBeTruthy();
    expect(
      screen.getByText("La búsqueda pasó de 3 a 5 evidencias."),
    ).toBeTruthy();
    expect(screen.getByText("Entregó la respuesta")).toBeTruthy();
    // Nunca se inventa razonamiento del modelo.
    expect(screen.queryByText(/El modelo analizó la evidencia/)).toBeNull();
  });

  it("agrupa la evidencia por documento sin repetir el nombre del PDF", () => {
    renderExplained();
    expect(screen.getByText("Evidencia utilizada")).toBeTruthy();
    expect(screen.getAllByText("Rec2_Rules_dapp_C.pdf").length).toBe(1);
    expect(screen.getAllByText("Cat10_dapp_C.pdf").length).toBe(1);
    expect(screen.getAllByText(/2 evidencias utilizadas/).length).toBe(2);
    expect(screen.getAllByText("Fuente sin nombre").length).toBe(1);
    expect(screen.queryByText("Documento sin título")).toBeNull();
  });

  it("muestra la decisión aplicada con efecto y resultado", () => {
    renderExplained();
    expect(screen.getByText("Decisiones de JEV")).toBeTruthy();
    expect(screen.getByText("1 decisión modificó la ejecución.")).toBeTruthy();
    expect(screen.getByText("Buscar más evidencia")).toBeTruthy();
    expect(screen.getByText(/faltaba: ¿Se puede responder con la evidencia actual\?/)).toBeTruthy();
    expect(screen.getByText(/Evidencia: 3 a 5/)).toBeTruthy();
    // La decisión observacional no aparece como intervención.
    expect(screen.queryByText("2 decisiones modificaron la ejecución.")).toBeNull();
  });

  it("explica la verificación parcial sin mostrar claves internas", () => {
    renderExplained();
    expect(screen.getByText("Verificación de la respuesta")).toBeTruthy();
    expect(
      screen.getByText(
        /La respuesta está respaldada por las fuentes recuperadas, pero una comprobación secundaria no pudo ejecutarse\./,
      ),
    ).toBeTruthy();
    expect(screen.getByText("Respaldo documental confirmado")).toBeTruthy();
    expect(screen.getByText("La verificación de respuesta no estuvo disponible")).toBeTruthy();
    expect(screen.queryByText("answer_gate: warn")).toBeNull();
    expect(screen.queryByText("grounding: ok")).toBeNull();
  });

  it("el botón de diagnóstico lleva al modo técnico", async () => {
    const user = userEvent.setup();
    const calls: string[] = [];
    const traceability = parseTraceability(TRACEABILITY);
    if (!traceability) throw new Error("fixture inválido");
    render(
      <ExperienceStory
        story={buildExecutionStory(FLOW)}
        traceability={traceability}
        onOpenTechnical={() => calls.push("technical")}
      />,
    );
    await user.click(screen.getByText("Ver diagnóstico JEV"));
    expect(calls).toEqual(["technical"]);
  });
});

describe("ExperienceStory — JEV sin intervención", () => {
  it("dice que revisó sin cambios y no inventa una intervención", () => {
    const traceability = parseTraceability({
      ...TRACEABILITY,
      decisions: [TRACEABILITY.decisions[1]],
      timeline: TRACEABILITY.timeline.filter((event) => event.type !== "RETRIEVAL_EXPANDED"),
      judgments: [
        {
          judgment_id: "pre_generation:next_action",
          phase: "pre_generation",
          question_code: "next_action",
          type: "choice",
          display: { outcome_key: "generate", probability: 0.9, confidence_band: "high" },
          alternatives: [{ key: "generate", probability: 0.9 }],
        },
        {
          judgment_id: "pre_generation:answerable_from_current_evidence",
          phase: "pre_generation",
          question_code: "answerable_from_current_evidence",
          type: "noul",
          display: { outcome_key: "yes", probability: 0.7, confidence_band: "medium" },
          alternatives: [],
        },
      ],
    });
    if (!traceability) throw new Error("fixture inválido");
    render(
      <ExperienceStory story={buildExecutionStory(FLOW)} traceability={traceability} />,
    );
    expect(screen.getByText(/JEV revisó la ejecución \(2 comprobaciones\)\. No fueron necesarios cambios\./)).toBeTruthy();
    expect(screen.queryByText(/modificó la ejecución/)).toBeNull();
  });
});
