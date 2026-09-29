import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { AgentKnowledgeSection, VISIBLE_SOURCES } from "./AgentKnowledgeSection";
import type { KnowledgeSource } from "./types";

const LONG_NAME =
  "Emergency Flexibility for Conditions on Existing tickets Data App Overview_dapp_C.pdf";

function makeSource(index: number, overrides: Partial<KnowledgeSource> = {}): KnowledgeSource {
  return {
    id: `s${index}`,
    name: `Fuente ${index}`,
    type: "file",
    status: "ready",
    document_count: index,
    last_sync: null,
    knowledge_base_id: "kb1",
    ...overrides,
  };
}

function renderSection(
  sources: KnowledgeSource[],
  selectedIds: string[],
  loading = false,
) {
  return render(
    <AgentKnowledgeSection
      sources={sources}
      selectedIds={selectedIds}
      jobs={[]}
      loading={loading}
      capabilitySummary="Consultar conocimiento"
      onToggle={vi.fn()}
      onSetSelected={vi.fn()}
      onIndex={vi.fn()}
    />,
  );
}

describe("AgentKnowledgeSection", () => {
  it("acota la lista a 5 filas y permite ver todas", async () => {
    const user = userEvent.setup();
    const sources = Array.from({ length: 8 }, (_, i) => makeSource(i + 1));
    renderSection(
      sources,
      sources.map((source) => source.id),
    );

    const list = screen.getByTestId("agent-knowledge-list");
    expect(within(list).getAllByRole("listitem")).toHaveLength(VISIBLE_SOURCES);
    const expand = screen.getByRole("button", { name: "Ver las 8 fuentes" });
    expect(expand).toHaveAttribute("aria-expanded", "false");

    await user.click(expand);
    expect(within(list).getAllByRole("listitem")).toHaveLength(8);
    await user.click(screen.getByRole("button", { name: "Ver menos" }));
    expect(within(list).getAllByRole("listitem")).toHaveLength(VISIBLE_SOURCES);
  });

  it("expone el nombre completo de una fuente larga sin romper el layout", () => {
    const long = makeSource(1, { name: LONG_NAME });
    renderSection([long], [long.id]);

    const name = screen.getByTitle(LONG_NAME);
    expect(name).toHaveTextContent(LONG_NAME);
    expect(name.className).toContain("truncate");
    // El li debe poder encogerse: sin min-w-0 el track del grid crecía al
    // nombre completo y el panel izquierdo sacaba scroll horizontal.
    expect(name.closest("li")?.className).toContain("min-w-0");
  });

  it("muestra skeleton mientras cargan las fuentes", () => {
    renderSection([], ["s1"], true);

    expect(screen.getByTestId("agent-knowledge-loading")).toBeInTheDocument();
    expect(screen.queryByTestId("agent-knowledge-list")).toBeNull();
    expect(screen.getByText("Cargando fuentes…")).toBeInTheDocument();
  });
});
