import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import KnowledgeQualityPage from "./Quality";

const api = vi.hoisted(() => vi.fn());
const fetchKnowledgeHealth = vi.hoisted(() => vi.fn());
const fetchKnowledgeQuality = vi.hoisted(() => vi.fn());
const fetchKnowledgeConflicts = vi.hoisted(() => vi.fn());
const fetchKnowledgeGaps = vi.hoisted(() => vi.fn());
const fetchQuestions = vi.hoisted(() => vi.fn());

vi.mock("../../api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../../api")>();
  return { ...actual, api };
});

vi.mock("../../auth", () => ({
  useAuth: () => ({ session: { token: "t", organizationId: "o" } }),
}));

vi.mock("../../lib/knowledgeModel", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../../lib/knowledgeModel")>();
  return {
    ...actual,
    fetchKnowledgeHealth,
    fetchKnowledgeQuality,
    fetchKnowledgeConflicts,
    fetchKnowledgeGaps,
  };
});

vi.mock("../../lib/knowledgeLearning", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../../lib/knowledgeLearning")>();
  return { ...actual, fetchQuestions };
});

beforeEach(() => {
  api.mockReset();
  fetchKnowledgeHealth.mockResolvedValue({
    overall: null,
    measured_dimensions: 0,
    total_dimensions: 5,
    dimensions: [],
    state: "unmeasured",
    computed_at: new Date().toISOString(),
  });
  fetchKnowledgeQuality.mockResolvedValue({
    issues: [],
    total: 0,
    by_severity: {},
    generated_at: new Date().toISOString(),
  });
  fetchKnowledgeConflicts.mockResolvedValue({ conflicts: [] });
  fetchKnowledgeGaps.mockResolvedValue({ gaps: [] });
  fetchQuestions.mockResolvedValue({ questions: [] });
  api.mockResolvedValue([]);
});

describe("KnowledgeQualityPage · Mejorar", () => {
  it("abre la bandeja y distingue no evaluado de no hay problemas", async () => {
    render(
      <MemoryRouter initialEntries={["/knowledge/improve"]}>
        <KnowledgeQualityPage />
      </MemoryRouter>,
    );

    expect(await screen.findByTestId("quality-inbox")).toBeInTheDocument();
    expect(screen.getByText(/Calidad aún no evaluada/)).toBeInTheDocument();
    expect(screen.queryByText("No hay problemas conocidos.")).not.toBeInTheDocument();
  });
});
