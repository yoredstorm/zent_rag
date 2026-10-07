// =============================================================================
// TraceV2Story / TraceV2Technical — render de la vista canónica v2
// =============================================================================
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { parseTraceabilityV2 } from "../traceabilityV2";
import { TraceV2Story } from "./TraceV2Story";
import { TraceV2Technical } from "./TraceV2Technical";

const TRACE = {
  schema_version: 2,
  execution: {
    kind: "query",
    id: "q-1",
    question: "¿Qué código aplica?",
    status: "completed",
    delivered: true,
    method: "rag",
  },
  routing: { route: "Documentos", decider: "JEV" },
  knowledge: { strategy: "hybrid" },
  retrieval: { rounds: [{ attempt: 1, strategy: "hybrid", evidence: 5, sufficient: true }] },
  evidence: {
    collection: "complete",
    counts: {
      documents_retrieved: 5,
      documents_used: 5,
      evidence_retrieved: 8,
      evidence_deduplicated: 3,
      evidence_unique: 5,
      evidence_selected: 5,
      evidence_used: 5,
      evidence_cited: 4,
    },
    dedup: { merged: 3, exact: 2, overlap: 1, semantic: 0 },
    citations_summary: { references: 5, cited_references: 5, unique_cited: 4, collapsed: 1, dangling: [] },
    documents: [
      {
        document_key: "src_a",
        canonical_source_id: "src_a",
        document_name: "rules.pdf",
        display_name: "rules.pdf",
        name_missing: false,
        evidence_count: 2,
        used_count: 2,
        cited_count: 1,
        items: [
          {
            evidence_id: "E1",
            canonical_source_id: "src_a",
            document_name: "rules.pdf",
            display_name: "rules.pdf",
            page: 18,
            excerpt: "Carrier Code aplicable al record dos.",
            used: true,
            cited: true,
            merged_count: 1,
            hit_count: 2,
            dedup_kind: "overlap",
            raw_hits: [],
          },
        ],
      },
    ],
    canonical_evidence: [],
  },
  jev: {
    executed: true,
    mode: "on",
    calls: 1,
    checks: 4,
    judgments_count: 2,
    material_intervention: false,
    changed_route: false,
    requested_more_evidence: false,
    blocked_generation: false,
    decisions: [
      {
        decision_id: "decision:1",
        action: "generate",
        action_applied: true,
        classification: "OBSERVATIONAL",
        material: false,
        reason_codes: ["default"],
      },
    ],
    judgments: [
      {
        id: "tool",
        judgment_id: "pre_generation:tool",
        phase: "pre_generation",
        question_code: "tool",
        type: "choice",
        answer: "none",
        interpretation: {
          outcome_key: "none",
          selected_probability: 0.75,
          confidence: 0.49,
          margin: 0.5,
          entropy: 0.81,
          band: "low",
          verdict: "UNCERTAIN",
          options: [
            { key: "none", probability: 0.75, selected: true },
            { key: "search_knowledge", probability: 0.25, selected: false },
          ],
        },
        raw: { type: "choice" },
      },
    ],
  },
  generation: {
    observed: true,
    skipped: false,
    model: "zent-default",
    calls: 2,
    answer_calls: 1,
    reasoning_calls: 1,
    revision_calls: 0,
    call_details: [
      { id: "llm-1", sequence: 1, purpose: "reasoning" },
      { id: "llm-2", sequence: 2, purpose: "answer_generation" },
    ],
    tokens: { input: 6687, output: 1068, total: 7755 },
    duration_ms: 6700,
    cost_usd: 0.001018,
  },
  controls: {
    controls: [
      {
        control_code: "MAX_TOKENS_REACHED",
        severity: "WARNING",
        recovered: true,
        material_effect: false,
        params: { impact: "RECOVERED_NO_IMPACT" },
      },
    ],
    fallbacks: { events: [], material: false, classes: {} },
  },
  verification: {
    status: "VERIFIED",
    explanation_codes: [{ code: "DOCUMENTARY_SUPPORT_CONFIRMED" }],
    checks: [{ key: "grounding", state: "ok" }],
    degradations: [],
    signals: { grounded: true, fallback_used: false, material_fallback: false },
    metrics: { quality: { value: 2.87 } },
  },
  memory: { observed: false, available: null },
  timing: { wall_clock_ms: 18089, accumulated_ms: 24332, parallel: true, breakdown: [{ code: "tools", ms: 24332 }] },
  cost: { total_usd: 0.001018, breakdown: [] },
  diagnostics: {
    items: [
      {
        code: "PROBABILITY_MISMATCH",
        severity: "WARNING",
        dimension: "consistency",
        material_effect: false,
        meaning_code: "confidence_conflict",
        impact_code: "no_content_impact",
        fix_code: "separate_probability_confidence",
        params: { selected_probability: 0.75, confidence: 0.49, outcome_key: "none" },
      },
      {
        code: "SOURCE_NAME_MISSING",
        severity: "WARNING",
        dimension: "metadata",
        material_effect: false,
        params: { canonical_source_id: "src_x" },
      },
    ],
    dimensions: {
      execution: { status: "ok", findings: 0 },
      evidence: { status: "ok", findings: 0 },
      jev: { status: "ok", findings: 0 },
      generation: { status: "notice", severity: "NOTICE", findings: 1 },
      verification: { status: "ok", findings: 0 },
      metadata: { status: "warning", severity: "WARNING", findings: 1 },
      consistency: { status: "warning", severity: "WARNING", findings: 1 },
    },
    consistency: { status: "partial", findings: 2, response_quality: "VERIFIED" },
    overall: { status: "notice", severity: "NOTICE", findings: 3 },
  },
  presentation: {
    headline: { code: "RESPONSE_SUPPORTED", params: {} },
    support: {
      documents_used: 5,
      evidence_unique: 5,
      evidence_used: 5,
      evidence_cited: 4,
      collection: "complete",
    },
    journey: [
      {
        id: "journey:1:knowledge_searched",
        kind: "KNOWLEDGE_SEARCHED",
        sequence: 1,
        params: { retrieved: 8, deduplicated: 3, unique: 5 },
      },
      {
        id: "journey:2:jev_checked",
        kind: "JEV_CHECKED",
        sequence: 2,
        params: { checks: 4, material_intervention: false, changed_route: false },
      },
      {
        id: "journey:3:answer_generated",
        kind: "ANSWER_GENERATED",
        sequence: 3,
        params: { calls: 1 },
      },
    ],
    explanations: [
      { code: "MODEL_CALLS_PURPOSES", params: { calls: 2, reasoning_calls: 1, answer_calls: 1 } },
      { code: "MAX_TOKENS_RECOVERY", params: { impact: "RECOVERED_NO_IMPACT" } },
      { code: "USED_NOT_CITED", params: { used: 5, cited: 4, difference: 1 } },
    ],
    metric_refs: ["selected_probability", "confidence"],
    glossary_refs: ["jev"],
  },
  timeline: [],
};

describe("TraceV2Story", () => {
  it("resume la ejecución en lenguaje humano", () => {
    const trace = parseTraceabilityV2(TRACE);
    expect(trace).not.toBeNull();
    if (!trace) return;
    render(<TraceV2Story trace={trace} onOpenTechnical={vi.fn()} />);

    expect(screen.getByText("Respuesta respaldada")).toBeInTheDocument();
    expect(screen.getByText("5 documentos · 5 evidencias únicas")).toBeInTheDocument();
    expect(
      screen.getByText("Revisó 4 decisiones y mantuvo el camino original"),
    ).toBeInTheDocument();
    expect(screen.getByText("Respaldo confirmado")).toBeInTheDocument();
    expect(screen.getByText("18.1 s")).toBeInTheDocument();
    expect(screen.getByText("USD 0.001018")).toBeInTheDocument();
  });

  it("narra el journey sin inventar pasos", () => {
    const trace = parseTraceabilityV2(TRACE);
    if (!trace) return;
    render(<TraceV2Story trace={trace} onOpenTechnical={vi.fn()} />);
    expect(screen.getByText("Cómo llegó Zent a esta respuesta")).toBeInTheDocument();
    expect(
      screen.getByText(
        "Encontró 8 fragmentos. 3 eran duplicados o se solapaban. Quedaron 5 evidencias útiles.",
      ),
    ).toBeInTheDocument();
    expect(screen.getByText("Buscó conocimiento")).toBeInTheDocument();
    expect(screen.getByText("Generó la respuesta")).toBeInTheDocument();
  });

  it("explica por qué hubo dos llamadas y por qué el límite no afectó", () => {
    const trace = parseTraceabilityV2(TRACE);
    if (!trace) return;
    render(<TraceV2Story trace={trace} onOpenTechnical={vi.fn()} />);
    expect(screen.getByText("¿Por qué hubo varias llamadas al modelo?")).toBeInTheDocument();
    expect(
      screen.getByText("Hubo 2 llamadas: 1 se usó para razonamiento interno y 1 para generar la respuesta final."),
    ).toBeInTheDocument();
    expect(screen.getByText("¿Qué pasó con el límite de generación?")).toBeInTheDocument();
    expect(screen.getByText("¿Por qué se utilizaron más evidencias de las que se citaron?")).toBeInTheDocument();
  });

  it("separa calidad de respuesta de consistencia de telemetría", () => {
    const trace = parseTraceabilityV2(TRACE);
    if (!trace) return;
    render(<TraceV2Story trace={trace} onOpenTechnical={vi.fn()} />);
    expect(screen.getByText("Diagnóstico de la ejecución")).toBeInTheDocument();
    expect(screen.getByText(/Respuesta:/)).toBeInTheDocument();
    expect(screen.getByText(/Trazabilidad:/)).toBeInTheDocument();
    expect(screen.getByText("Parcialmente consistente")).toBeInTheDocument();
  });

  it("muestra cada diagnóstico con las tres preguntas y el código al final", async () => {
    const trace = parseTraceabilityV2(TRACE);
    if (!trace) return;
    render(<TraceV2Story trace={trace} onOpenTechnical={vi.fn()} />);
    await userEvent.click(screen.getByText("Probabilidad y confianza no coinciden"));
    expect(screen.getByText(/Qué significa:/)).toBeInTheDocument();
    expect(screen.getByText(/¿Afectó la respuesta\?:/)).toBeInTheDocument();
    expect(screen.getByText(/Qué debería corregirse:/)).toBeInTheDocument();
    expect(screen.getByText("PROBABILITY_MISMATCH")).toBeInTheDocument();
  });

  it("abre la evidencia y marca las citadas", async () => {
    const trace = parseTraceabilityV2(TRACE);
    if (!trace) return;
    render(<TraceV2Story trace={trace} onOpenTechnical={vi.fn()} />);
    await userEvent.click(screen.getAllByText("Mostrar")[0]);
    expect(screen.getByText("rules.pdf")).toBeInTheDocument();
    expect(screen.getByText("Citada")).toBeInTheDocument();
    expect(screen.getByText("Carrier Code aplicable al record dos.")).toBeInTheDocument();
  });

  it("muestra el fast path determinista con su ahorro", () => {
    const raw = {
      ...TRACE,
      execution: {
        ...TRACE.execution,
        mode: "DETERMINISTIC_FAST_PATH",
        fast_path: {
          eligible: true,
          reason: "SUPPORTED_DECISION",
          operation: "POSITIONAL_MATCH",
          result: "MATCH",
          execution_mode: "DETERMINISTIC_FAST_PATH",
          llm_calls: 0,
          llm_calls_avoided: 2,
          tokens_avoided: 3500,
          latency_ms: 85,
          verification: { status: "VERIFIED_DETERMINISTIC" },
        },
      },
    };
    const trace = parseTraceabilityV2(raw);
    if (!trace) return;
    render(<TraceV2Story trace={trace} onOpenTechnical={vi.fn()} />);
    expect(screen.getByText("Fast path determinista")).toBeInTheDocument();
    expect(
      screen.getByText("0 llamadas LLM · 2 evitadas · 3500 tokens evitados"),
    ).toBeInTheDocument();
    expect(screen.getByText("85 ms")).toBeInTheDocument();
  });

  it("permite abrir la vista técnica", async () => {
    const trace = parseTraceabilityV2(TRACE);
    if (!trace) return;
    const onOpenTechnical = vi.fn();
    render(<TraceV2Story trace={trace} onOpenTechnical={onOpenTechnical} />);
    await userEvent.click(screen.getByText("Ver detalles técnicos"));
    expect(onOpenTechnical).toHaveBeenCalledTimes(1);
  });

  it("muestra ejes de uso y juicios superados", async () => {
    const raw = {
      ...TRACE,
      evidence: {
        ...TRACE.evidence,
        counts: {
          ...TRACE.evidence.counts,
          evidence_used_for_reasoning: 2,
          evidence_used_for_decision: 3,
        },
        documents: [
          {
            ...TRACE.evidence.documents[0],
            decision_count: 1,
            items: TRACE.evidence.documents[0].items.map((item) => ({
              ...item,
              used_for_decision: true,
            })),
          },
        ],
      },
      jev: {
        ...TRACE.jev,
        requested_more_evidence: true,
        superseded_count: 1,
        resolution: {
          label: "DecisionEnvelope MATCH",
          authority: true,
          premise_closed: true,
        },
        judgments: TRACE.jev.judgments.map((judgment) => ({
          ...judgment,
          status: "SUPERSEDED",
          superseded_by: "DecisionEnvelope MATCH",
        })),
      },
    };
    const trace = parseTraceabilityV2(raw);
    if (!trace) return;
    render(<TraceV2Story trace={trace} onOpenTechnical={vi.fn()} />);
    expect(screen.getByText(/3 usadas para la decisión/)).toBeInTheDocument();
    const evidenceToggle = screen.getByText("Evidencia utilizada").closest("button");
    if (evidenceToggle) await userEvent.click(evidenceToggle);
    expect(screen.getByText("Decisión")).toBeInTheDocument();
    const jevToggle = screen.getByText("Decisiones JEV").closest("button");
    if (jevToggle) await userEvent.click(jevToggle);
    expect(screen.getByText("Superado")).toBeInTheDocument();
    expect(screen.getAllByText(/superado por/).length).toBeGreaterThan(0);
  });
});

describe("TraceV2Technical", () => {
  it("muestra tarjetas semánticas con explicaciones y tiempos separados", () => {
    const trace = parseTraceabilityV2(TRACE);
    if (!trace) return;
    render(<TraceV2Technical trace={trace} />);
    expect(screen.getByText("GENERACIÓN")).toBeInTheDocument();
    expect(screen.getByText("TIEMPOS")).toBeInTheDocument();
    expect(screen.getByText("Tiempo real percibido")).toBeInTheDocument();
    expect(screen.getByText("Trabajo interno acumulado")).toBeInTheDocument();
    expect(screen.getByText("Sí (la suma puede superar el tiempo real)")).toBeInTheDocument();
    expect(screen.getByText("CALIDAD DE TELEMETRÍA")).toBeInTheDocument();
    expect(screen.getByText("Límite de generación alcanzado")).toBeInTheDocument();
    expect(screen.getByText(/Resuelto automáticamente/)).toBeInTheDocument();
  });
});

describe("Verificación separada decisión/narrativa", () => {
  const SPLIT_TRACE = {
    ...TRACE,
    verification: {
      ...TRACE.verification,
      status: "PARTIALLY_VERIFIED",
      signals: { grounded: false, fallback_used: false, material_fallback: false },
      decision_verification: {
        status: "VERIFIED",
        authoritative: true,
        deterministic: true,
        operation: "POSITIONAL_MATCH",
        result: "MATCH",
        canonical_rule_ids: ["rule:atpco"],
        premise_status: "SATISFIED",
        evidence_refs: ["E1"],
        rule_verification: "SUPPORTED",
        conflicts: [],
      },
      narrative_verification: {
        status: "TRUNCATED",
        truncated: true,
        warnings: ["MAX_TOKENS_REACHED"],
        citations_valid: null,
        explanation_complete: false,
        grounding_complete: false,
      },
      decision_grounding: "CONFIRMED",
      narrative_grounding: "BLOCKED",
    },
    presentation: {
      ...TRACE.presentation,
      headline: { code: "RESPONSE_DECISION_VERIFIED_NARRATIVE_PARTIAL", params: {} },
    },
  };

  it("muestra DECISIÓN y EXPLICACIÓN con estados independientes", () => {
    const trace = parseTraceabilityV2(SPLIT_TRACE);
    if (!trace) return;
    render(<TraceV2Story trace={trace} onOpenTechnical={vi.fn()} />);
    expect(
      screen.getAllByText("Decisión verificada · explicación parcialmente verificada").length,
    ).toBeGreaterThan(0);
    expect(screen.getByText("DECISIÓN")).toBeInTheDocument();
    expect(screen.getByText("Verificada determinísticamente")).toBeInTheDocument();
    expect(screen.getByText("POSITIONAL_MATCH")).toBeInTheDocument();
    expect(screen.getByText("MATCH")).toBeInTheDocument();
    expect(screen.getByText("EXPLICACIÓN")).toBeInTheDocument();
    expect(screen.getByText("Truncada por límite de generación")).toBeInTheDocument();
    expect(screen.getByText("MAX_TOKENS_REACHED")).toBeInTheDocument();
  });

  it("la vista técnica expone ambos groundings", () => {
    const trace = parseTraceabilityV2(SPLIT_TRACE);
    if (!trace) return;
    render(<TraceV2Technical trace={trace} />);
    expect(screen.getByText("Decisión")).toBeInTheDocument();
    expect(screen.getByText("Grounding de la decisión")).toBeInTheDocument();
    expect(screen.getByText("Grounding de la narrativa")).toBeInTheDocument();
  });

  it("la vista técnica muestra provenance de la regla ganadora", () => {
    const raw = {
      ...TRACE,
      execution: {
        ...TRACE.execution,
        mode: "DETERMINISTIC_FAST_PATH",
        fast_path: {
          eligible: true,
          operation: "POSITIONAL_MATCH",
          result: "MATCH",
          llm_calls: 0,
          llm_calls_avoided: 2,
          latency_ms: 85,
          verification: { status: "VERIFIED_DETERMINISTIC" },
          decision_evidence: {
            resolved: 5,
            unresolved: [],
            main_retrieval_hits: 0,
            decision_evidence_count: 5,
            documents_used_for_decision: 1,
          },
          winning_rule: {
            rule_id: "rule:rule:293d1234",
            source_ids: ["73080890"],
            document_ids: ["98e1703f"],
            pages: [11, 12],
            document_title: "Data Application For Record 2",
            parser_version: "pdfplumber-text-1.1",
          },
        },
      },
    };
    const trace = parseTraceabilityV2(raw);
    if (!trace) return;
    render(<TraceV2Technical trace={trace} />);
    expect(screen.getByText("Regla ganadora")).toBeInTheDocument();
    expect(screen.getByText("rule:293d1234")).toBeInTheDocument();
    expect(screen.getByText("Data Application For Record 2")).toBeInTheDocument();
    expect(screen.getByText("11, 12")).toBeInTheDocument();
    expect(screen.getByText("pdfplumber-text-1.1")).toBeInTheDocument();
    expect(screen.getByText("Evidencia de decisión")).toBeInTheDocument();
  });
});
