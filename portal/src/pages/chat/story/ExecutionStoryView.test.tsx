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
    expect(screen.getByText("deepseek-v3.2")).toBeTruthy();
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
