import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { WorkflowRunInspector, type RunDetail } from "./WorkflowRunInspector";

const RUN: RunDetail = {
  id: "run-1",
  status: "succeeded",
  steps: [
    {
      step_index: 0,
      step_type: "business_result",
      node_id: "br",
      node_type: "business_result",
      status: "succeeded",
      output: { result_id: "r1" },
    },
  ],
  actions: [
    { node_id: "br", node_type: "business_result", status: "succeeded", summary: { result_id: "r1" } },
  ],
  contributions: [
    { section: "knowledge", node_id: "kb", node_type: "kb_query", payload: { value: { count: 1, query: "stock" } } },
    { section: "data", node_id: "q", node_type: "query_business_data", payload: { value: { answer: "7 unidades" } } },
    { section: "artifacts", node_id: "br", node_type: "business_result", payload: { value: { id: "r1" } } },
  ],
  evidence_refs: [
    {
      section: "evidence_refs",
      node_id: "kb",
      node_type: "kb_query",
      label: "Política de descuentos",
      payload: { value: { evidence_id: "e1", label: "politica.pdf" } },
    },
  ],
  claim_refs: [],
  decisions: [
    {
      section: "decisions",
      node_id: "ask",
      node_type: "llm",
      label: "Riesgos",
      payload: { value: { risk: "high", reason: "mora" } },
    },
  ],
  findings: [],
  artifacts: [
    {
      section: "artifacts",
      node_id: "br",
      node_type: "business_result",
      payload: { value: { id: "r1", title: "Resumen" } },
    },
  ],
  chain_of_thought_exposed: false,
  story: ["Se inició el flujo.", "El agente analizó la situación: HIGH."],
  events: [
    { id: "ev1", kind: "run_started", payload: { run_mode: "full" } },
    { id: "ev2", kind: "node_finished", node_id: "br", payload: { status: "succeeded" } },
  ],
};

describe("WorkflowRunInspector — Execution Inspector", () => {
  it("muestra contexto, evidencia, decisiones, artefactos y acciones", () => {
    render(<WorkflowRunInspector run={RUN} />);
    expect(screen.getByTestId("wf-run-inspector")).toBeInTheDocument();
    expect(screen.getByTestId("wf-run-context")).toHaveTextContent("Datos y conocimiento (2)");
    expect(screen.getByTestId("wf-run-evidence")).toHaveTextContent("Evidencia y claims (1)");
    expect(screen.getByTestId("wf-run-evidence")).toHaveTextContent("Política de descuentos");
    expect(screen.getByTestId("wf-run-decisions")).toHaveTextContent("Decisiones y hallazgos (1)");
    expect(screen.getByTestId("wf-run-artifacts")).toHaveTextContent("Artefactos (1)");
    expect(screen.getByTestId("wf-run-actions")).toHaveTextContent("Acciones del run (1)");
    expect(screen.getByTestId("wf-run-actions")).toHaveTextContent("business_result");
    expect(screen.getByTestId("wf-run-events")).toHaveTextContent("Timeline del run (2)");
    expect(screen.getByTestId("wf-run-events")).toHaveTextContent("run_started");
    expect(screen.getByTestId("wf-run-story")).toHaveTextContent("El agente analizó la situación: HIGH");
  });

  it("no rompe sin contexto extra ni CoT", () => {
    render(<WorkflowRunInspector run={{ id: "r2", status: "succeeded", steps: [] }} />);
    expect(screen.getByTestId("wf-run-inspector")).toBeInTheDocument();
    expect(screen.queryByTestId("wf-run-evidence")).toBeNull();
    expect(screen.queryByTestId("wf-run-actions")).toBeNull();
    expect(screen.queryByText(/chain of thought/i)).toBeNull();
  });

  it("separa efectos sin doble, declarados y simulados", () => {
    render(
      <WorkflowRunInspector
        run={{
          ...RUN,
          effect_verification: {
            level: "UNVERIFIED",
            unverified: [{ node_id: "pay", node_type: "capability_call", label: "Cobrar" }],
            declared: [{ node_id: "mail", node_type: "notify", label: "Avisar" }],
            simulated: [{ node_id: "state", node_type: "state_set", label: "Guardar" }],
          },
        }}
      />,
    );
    expect(screen.getByTestId("wf-effect-verification")).toHaveTextContent("UNVERIFIED");
    expect(screen.getByTestId("wf-effects-unverified")).toHaveTextContent("Cobrar");
    expect(screen.getByTestId("wf-effects-declared")).toHaveTextContent("Avisar");
    expect(screen.getByTestId("wf-effects-simulated")).toHaveTextContent("Guardar");
  });

  it("clasifica plannedEffects viejos sin effect_verification", () => {
    render(
      <WorkflowRunInspector
        run={{
          ...RUN,
          planned_effects: [
            { node_id: "pay", node_type: "capability_call", planned: { kind: "capability" } },
          ],
        }}
      />,
    );
    expect(screen.getByTestId("wf-effect-verification")).toHaveTextContent("UNVERIFIED");
    expect(screen.getByTestId("wf-effects-unverified")).toHaveTextContent("pay");
  });
});
