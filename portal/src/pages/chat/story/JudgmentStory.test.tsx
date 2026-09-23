// =============================================================================
// JudgmentStory — render del juicio previo (§35-§44)
// =============================================================================
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { buildExecutionStory } from "../executionStory";
import { JevImpactCard, JudgmentPackCard, JudgmentUncertaintyNote } from "./JudgmentStory";

const FLOW = {
  flow_version: 2,
  status: "completed",
  timings: { total_ms: 1200 },
  steps: [],
  sources: [],
  jev_preflight: {
    mode: "on",
    summary: {
      calls: 2,
      judgments: 4,
      decisions_influenced: 2,
      uncertain_critical_judgments: 1,
      llm_escalations_avoided: 1,
      latency_ms: 61.4,
    },
    decisions: [
      {
        phase: "pre_generation",
        action: "generate_answer",
        tier: "small",
        allow_generation: true,
        applied: true,
        reasons: ["cheaper_tier_sufficient"],
        uncertain_critical: ["evidence_sufficient"],
      },
    ],
  },
  events: [
    {
      id: "jev-1",
      phase: "decision",
      kind: "jev_pack",
      status: "ok",
      duration_ms: 41.2,
      metrics: {
        phase: "pre_generation",
        judgment_count: 4,
        effects: ["state_reconstruction_activated", "expensive_model_avoided"],
        uncertain: ["evidence_sufficient"],
        readiness: {
          rows: [
            { key: "evidence", state: "ok", confidence: 0.94, source: "jev" },
            { key: "conflicts", state: "blocked", detail: "unresolved", source: "jev" },
          ],
        },
        questions: [
          {
            id: "analysis_complete",
            type: "noul",
            version: 1,
            decision: "yes",
            value: 0.97,
            certainty: 0.94,
            effect: "generation_allowed",
          },
          {
            id: "evidence_sufficient",
            type: "noul",
            version: 1,
            decision: "uncertain",
            value: 0.54,
            certainty: 0.08,
          },
          {
            id: "needs_state_reconstruction",
            type: "noul",
            version: 1,
            decision: "yes",
            value: 0.97,
            certainty: 0.94,
            effect: "state_reconstruction_activated",
          },
          {
            id: "generation_tier",
            type: "choice",
            version: 1,
            decision: "small",
            confidence: 0.88,
            distribution: { probabilities: { small: 0.88, standard: 0.08 } },
            effect: "generation_tier_small",
          },
        ],
      },
      technical: { mode: "on", model: "jev-latest", question_count: 4 },
      decision: {
        reason_codes: ["cheaper_tier_sufficient"],
        action: "generate_answer",
        tier: "small",
        allow_generation: true,
        applied: true,
      },
    },
  ],
};

describe("JudgmentPackCard", () => {
  it("muestra el pack agrupado con su costo de una llamada", () => {
    const [pack] = buildExecutionStory(FLOW).judgmentPacks;
    render(<JudgmentPackCard pack={pack} />);
    expect(screen.getByText("JEV · Antes de generar")).toBeInTheDocument();
    expect(screen.getByText(/4 preguntas · 1 llamada · 41 ms/)).toBeInTheDocument();
    // El tier aparece en el badge del pack y en el juicio de nivel de generación.
    expect(screen.getAllByText("Modelo pequeño").length).toBeGreaterThan(0);
  });

  it("declara el efecto de cada juicio que cambió algo (§40)", () => {
    const [pack] = buildExecutionStory(FLOW).judgmentPacks;
    render(<JudgmentPackCard pack={pack} />);
    expect(
      screen.getAllByText("Efecto: activó la reconstrucción de estados").length,
    ).toBeGreaterThan(0);
    expect(screen.getAllByText("Efecto: evitó el modelo caro").length).toBeGreaterThan(0);
  });

  it("no disfraza un juicio incierto de veredicto (§44)", () => {
    const [pack] = buildExecutionStory(FLOW).judgmentPacks;
    render(<JudgmentPackCard pack={pack} />);
    expect(screen.getByText("Juicio incierto")).toBeInTheDocument();
    expect(screen.getByText("evidence sufficient")).toBeInTheDocument();
    expect(screen.getByText("Incierto")).toBeInTheDocument();
  });

  it("muestra la matriz de preparación antes de generar (§27)", () => {
    const [pack] = buildExecutionStory(FLOW).judgmentPacks;
    render(<JudgmentPackCard pack={pack} />);
    expect(screen.getByText("Preparación antes de generar")).toBeInTheDocument();
    expect(screen.getByText("Evidencia")).toBeInTheDocument();
    expect(screen.getByText("Listo")).toBeInTheDocument();
    expect(screen.getByText("Bloqueado")).toBeInTheDocument();
  });

  it("expone las preguntas en lenguaje humano, no en jerga", () => {
    const [pack] = buildExecutionStory(FLOW).judgmentPacks;
    render(<JudgmentPackCard pack={pack} />);
    expect(screen.getByText("Ver las 4 preguntas")).toBeInTheDocument();
    expect(screen.getByText("¿El análisis está completo?")).toBeInTheDocument();
    expect(screen.getByText("¿Necesita reconstruir el estado?")).toBeInTheDocument();
  });
});

describe("JevImpactCard", () => {
  it("resume el impacto del juicio previo (§43)", () => {
    const impact = buildExecutionStory(FLOW).jevImpact;
    render(<JevImpactCard impact={impact!} />);
    expect(screen.getByText("Zent hizo 4 comprobaciones antes de generar")).toBeInTheDocument();
    expect(screen.getByText("Decisiones influidas")).toBeInTheDocument();
    expect(screen.getByText(/razonamiento generativo avanzado/)).toBeInTheDocument();
  });

  it("explica la incertidumbre cuando existe (§44)", () => {
    const impact = buildExecutionStory(FLOW).jevImpact;
    render(<JudgmentUncertaintyNote impact={impact!} />);
    expect(screen.getByText("Juicio incierto")).toBeInTheDocument();
    expect(screen.getByText(/quedó sin veredicto claro/)).toBeInTheDocument();
  });

  it("no muestra aviso de incertidumbre si todo fue concluyente", () => {
    const flow = {
      ...FLOW,
      jev_preflight: {
        ...FLOW.jev_preflight,
        summary: { ...FLOW.jev_preflight.summary, uncertain_critical_judgments: 0 },
        decisions: [],
      },
    };
    const impact = buildExecutionStory(flow).jevImpact;
    const { container } = render(<JudgmentUncertaintyNote impact={impact!} />);
    expect(container).toBeEmptyDOMElement();
  });
});
