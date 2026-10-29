import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it } from "vitest";
import { HealthSummary } from "./HealthSummary";
import type { KnowledgeHealth } from "../../lib/knowledgeModel";

const narrativeHealth: KnowledgeHealth = {
  overall: 52,
  measured_dimensions: 4,
  total_dimensions: 8,
  not_applicable_dimensions: 1,
  scoring_profile: "narrative",
  dimensions: [
    {
      key: "coverage",
      label: "Cobertura de evidencia",
      score: 100,
      weight: 0.2,
      measured: true,
      applicable: true,
      reason: "109 de 109 objetos tienen evidencia.",
      formula: "(objetos con evidencia / objetos evaluables) * 100",
      signals: {},
      missing: [],
      issues: [],
      updated_at: null,
      trend: null,
    },
    {
      key: "rules_metrics",
      label: "Reglas y métricas",
      score: null,
      weight: 0.15,
      measured: false,
      applicable: false,
      reason: "No aplica: el conocimiento cargado es narrativo/educativo.",
      formula: "",
      signals: {},
      missing: [],
      issues: [],
      updated_at: null,
      trend: null,
    },
    {
      key: "human_validation",
      label: "Validación humana",
      score: null,
      weight: 0.1,
      measured: false,
      applicable: true,
      reason: "No evaluado: aún no hay revisión humana registrada.",
      formula: "",
      signals: {},
      missing: ["revisión humana"],
      issues: [],
      updated_at: null,
      trend: null,
    },
  ],
  state: "partial",
  computed_at: new Date().toISOString(),
};

describe("HealthSummary", () => {
  it("explica perfil narrativo, no aplica y no evaluado", () => {
    render(
      <MemoryRouter>
        <HealthSummary health={narrativeHealth} />
      </MemoryRouter>,
    );

    expect(screen.getByText(/Calidad.*52 de 100/)).toBeInTheDocument();
    expect(screen.getByText(/Perfil narrativo/)).toBeInTheDocument();
    expect(screen.getByText("No aplica")).toBeInTheDocument();
    expect(screen.getByText("No medido")).toBeInTheDocument();
    expect(
      screen.getAllByText(/no aplica\(n\) a este tipo de documento/).length,
    ).toBeGreaterThan(0);
  });
});
