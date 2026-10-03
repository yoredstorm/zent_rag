// =============================================================================
// LearningSessionView — composición de la experiencia de aprendizaje
// =============================================================================
import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { LearningSessionDetail } from "../../lib/knowledgeSessions";
import { LearningSessionView } from "./LearningSessionView";

const state = vi.hoisted(() => ({
  current: {} as Record<string, unknown>,
}));

vi.mock("./useLearningSession", () => ({
  useLearningSession: () => state.current,
}));

function detail(overrides: Partial<LearningSessionDetail> = {}): LearningSessionDetail {
  return {
    session_id: "sess-1",
    organization_id: "org-1",
    workspace_id: null,
    title: "Aprendiendo 14 fuentes",
    origin: "upload",
    status: "completed",
    stage: "learned",
    stage_label: "Aprendido",
    stage_technical: "indexes",
    stages: [
      { key: "reading", label: "Leyendo", technical: "parser" },
      { key: "understanding", label: "Entendiendo", technical: "semantic units" },
      { key: "organizing", label: "Organizando", technical: "entity resolution" },
      { key: "connecting", label: "Conectando", technical: "knowledge graph" },
      { key: "verifying", label: "Verificando", technical: "evidence linking" },
      { key: "learned", label: "Aprendido", technical: "indexes" },
    ],
    source_count: 14,
    available_sources: 14,
    completed_sources: 14,
    failed_sources: 0,
    metrics: {},
    knowledge_delta: {},
    delta_totals: {},
    totals_before: {},
    totals_after: {},
    warnings: 0,
    errors: 0,
    started_at: null,
    available_at: null,
    completed_at: null,
    sealed_at: null,
    created_at: null,
    updated_at: null,
    is_available: true,
    sources: [
      {
        id: "row-1",
        session_id: "sess-1",
        source_id: "src-1",
        job_id: "job-1",
        name: "Rec4_dapp_C.pdf",
        source_type: "file",
        status: "completed",
        stage: "learned",
        stage_label: "Aprendido",
        stats: { pages: 27, entities: 43, facts: 68, relationships: 19, evidence: 91 },
        error: null,
        available_at: null,
        completed_at: "2026-10-01T00:00:00+00:00",
        created_at: null,
        updated_at: null,
      },
    ],
    ...overrides,
  };
}

function renderView() {
  return render(
    <MemoryRouter>
      <LearningSessionView sessionId="sess-1" />
    </MemoryRouter>,
  );
}

describe("LearningSessionView", () => {
  beforeEach(() => {
    state.current = {
      detail: detail(),
      events: [],
      graph: { session_id: "sess-1", nodes: [], edges: [] },
      metrics: { entities: 286, relationships: 731, facts: 1428 },
      delta: { new_entities: 412, new_facts: 1842, new_relationships: 763 },
      discoveries: [],
      stage: "learned",
      connected: false,
      loading: false,
      error: "",
      lastEventAt: null,
      active: false,
      refresh: () => undefined,
    };
  });

  it("compone estado, hitos, descubrimientos, fuentes, pulse y resumen final", () => {
    renderView();
    expect(screen.getByTestId("learning-session")).toBeInTheDocument();
    expect(screen.getByTestId("learning-hero")).toBeInTheDocument();
    expect(screen.getByTestId("knowledge-pulse")).toBeInTheDocument();
    expect(screen.getByTestId("learning-stages")).toBeInTheDocument();
    expect(screen.getByTestId("learning-milestones")).toBeInTheDocument();
    expect(screen.getByTestId("what-zent-is-learning")).toBeInTheDocument();
    expect(screen.getByTestId("session-sources")).toBeInTheDocument();
    expect(screen.getByTestId("learning-summary")).toBeInTheDocument();
    // La evolución de la fuente muestra hitos reales, no "100%".
    expect(screen.getByText(/27/)).toBeInTheDocument();
    expect(screen.queryByText("100% completado")).toBeNull();
  });

  it("traduce el fallo parcial a lenguaje humano y explica la recuperación", () => {
    state.current = {
      ...state.current,
      detail: detail({ status: "partial", failed_sources: 1 }),
    };
    renderView();
    expect(screen.getByText(/1 necesita atención/)).toBeInTheDocument();
    expect(
      screen.getByText(/El resto del conocimiento está disponible/),
    ).toBeInTheDocument();
    expect(screen.getAllByText("Aprendizaje parcial").length).toBeGreaterThan(0);
  });

  it("mientras aprende muestra 'ZENT está aprendiendo' y la sesión en vivo", () => {
    state.current = {
      ...state.current,
      detail: detail({ status: "learning", completed_sources: 0 }),
      active: true,
      connected: true,
      stage: "connecting",
    };
    renderView();
    expect(screen.getByText("ZENT está aprendiendo")).toBeInTheDocument();
    expect(screen.getAllByText("En vivo").length).toBeGreaterThan(0);
    expect(screen.queryByTestId("learning-summary")).toBeNull();
  });

  it("muestra hitos y reencuentros cuando hay eventos reales", () => {
    state.current = {
      ...state.current,
      detail: detail({ status: "learning", completed_sources: 3 }),
      active: true,
      events: [
        {
          seq: 1,
          session_id: "sess-1",
          source_id: "src-1",
          event_type: "RELATIONSHIP_DISCOVERED",
          stage: "connecting",
          severity: "info",
          message: "ZENT descubrió una relación",
          payload: { subject: "Record 4", object: "Record 2", related: true },
          aggregate: false,
          created_at: new Date().toISOString(),
        },
        {
          seq: 2,
          session_id: "sess-1",
          source_id: "src-1",
          event_type: "ENTITY_MATCHED",
          stage: "organizing",
          severity: "info",
          message: "ZENT reconoció una entidad que ya conocía: Record 4",
          payload: { name: "Record 4", entity_type: "record" },
          aggregate: false,
          created_at: new Date().toISOString(),
        },
      ],
    };
    renderView();
    expect(
      screen.getByText(/ZENT conectó dos áreas que ya conocía/)
    ).toBeInTheDocument();
    expect(screen.getByTestId("knowledge-matches")).toBeInTheDocument();
    expect(screen.getByText("Record 4")).toBeInTheDocument();
  });
});
