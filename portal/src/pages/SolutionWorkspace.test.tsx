import { fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";
import {
  SolutionWorkspaceView,
  type SolutionWorkspaceData,
} from "./SolutionWorkspace";

const DATA: SolutionWorkspaceData = {
  solution: {
    record_id: "sol-1",
    solution_id: "mentor_python",
    name: "Mentor de Python",
    description: "Acompaña práctica con progreso",
    version: "1.2.0",
    status: "draft",
    roles: [{ role_ref: "mentor_practica", version: "1.0.0" }],
    agents: [{ agent_ref: "mentor_agent", name: "Mentor" }],
    workflows: [{ workflow_ref: "mentor_cycle", name: "Ciclo" }],
    expected_outcomes: [{ name: "plan activo", target: "> 0" }],
    requirements: ["knowledge_base"],
  },
  materialization: {
    solution_id: "sol-1",
    status: "READY",
    artifacts: {
      workflow: { id: "wf-1" },
      role: { id: "role-1" },
      agent: { id: "agent-1" },
    },
  },
  workflow: { id: "wf-1", name: "Ciclo de mentoría", status: "draft" },
  gate: {
    allowed: false,
    state: "BLOCKED",
    required_level: "simulation",
    graph_hash: "graph-hash-123",
    semantic_plan_hash: "plan-hash-123",
    capability_snapshot_hash: "snapshot-hash-123",
    blockers: [{ code: "certification_required", message: "Falta un certificado." }],
  },
};

function renderView(overrides: Partial<SolutionWorkspaceData> = {}, onPublish = vi.fn()) {
  const data = { ...DATA, ...overrides };
  const utils = render(
    <MemoryRouter>
      <SolutionWorkspaceView data={data} mode="guided" onMode={vi.fn()} onPublish={onPublish} />
    </MemoryRouter>,
  );
  return { ...utils, onPublish };
}

describe("SolutionWorkspace", () => {
  it("muestra el estado real de solución, proceso y gate", () => {
    renderView();
    expect(screen.getByTestId("solution-status-bar")).toHaveTextContent("Mentor de Python");
    expect(screen.getByTestId("solution-status-bar")).toHaveTextContent("draft");
    expect(screen.getByTestId("solution-gate-state")).toHaveTextContent("Publicación bloqueada");
    fireEvent.click(screen.getByTestId("solution-tab-proceso"));
    expect(screen.getByTestId("solution-publish")).toBeDisabled();
    expect(screen.getByTestId("solution-publish-blocked")).toHaveTextContent("certificado");
  });

  it("no publica si el gate no devuelve ALLOW", () => {
    const { onPublish } = renderView();
    fireEvent.click(screen.getByTestId("solution-tab-proceso"));
    fireEvent.click(screen.getByTestId("solution-publish"));
    expect(onPublish).not.toHaveBeenCalled();
  });

  it("habilita publicar solo cuando la política permite", () => {
    const { onPublish } = renderView({
      gate: { ...DATA.gate!, allowed: true, state: "ALLOW", blockers: [] },
    });
    fireEvent.click(screen.getByTestId("solution-tab-proceso"));
    fireEvent.click(screen.getByTestId("solution-publish"));
    expect(onPublish).toHaveBeenCalledTimes(1);
  });

  it("expone el primer paso cuando no hay materialización", () => {
    renderView({ materialization: null });
    expect(screen.getByTestId("solution-first-experience")).toHaveTextContent("materializa");
  });

  it("en avanzado muestra hashes del gate, en simple no", () => {
    render(
      <MemoryRouter>
        <SolutionWorkspaceView
          data={DATA}
          mode="advanced"
          onMode={vi.fn()}
          onPublish={vi.fn()}
        />
      </MemoryRouter>,
    );
    fireEvent.click(screen.getByTestId("solution-tab-proceso"));
    expect(screen.getByTestId("solution-release")).toHaveTextContent("graph-hash-123");
  });
});
