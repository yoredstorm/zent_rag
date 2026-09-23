import { fireEvent, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";
import { AgentSourcePicker, INDEXING_COPY } from "./AgentSourcePicker";
import { AgentTestChat } from "./AgentTestChat";
import type { IngestionJob, KnowledgeSource } from "./types";

const EMPTY: KnowledgeSource = {
  id: "s1",
  name: "Intl Fares.pdf",
  type: "file",
  status: "created",
  document_count: 0,
  last_sync: null,
};

const READY: KnowledgeSource = {
  ...EMPTY,
  document_count: 4,
  status: "indexed",
};

const RUNNING: IngestionJob = {
  id: "j1",
  job_type: "sync_source:file",
  status: "running",
  progress: 50,
  source_id: "s1",
};

describe("AgentSourcePicker", () => {
  it("muestra barra y copy cuando el job corre y no hay docs", () => {
    render(
      <MemoryRouter>
        <AgentSourcePicker
          sources={[EMPTY]}
          selectedIds={["s1"]}
          jobs={[RUNNING]}
          loading={false}
          onToggle={() => {}}
          onIndex={() => {}}
        />
      </MemoryRouter>,
    );
    expect(screen.getByTestId("source-indexing-copy")).toHaveTextContent(INDEXING_COPY);
    expect(screen.getByTestId("source-progress-s1")).toBeInTheDocument();
    expect(screen.getByText(/Indexando/)).toBeInTheDocument();
    expect(screen.queryByText("Aún no indexada")).toBeNull();
    expect(screen.queryByText("created")).toBeNull();
  });

  it("no dice Aún no indexada cuando hay documentos", () => {
    render(
      <MemoryRouter>
        <AgentSourcePicker
          sources={[READY]}
          selectedIds={["s1"]}
          jobs={[]}
          loading={false}
          onToggle={() => {}}
          onIndex={() => {}}
        />
      </MemoryRouter>,
    );
    expect(screen.queryByText("Aún no indexada")).toBeNull();
    expect(screen.getByText(/4 docs/)).toBeInTheDocument();
    expect(screen.queryByTestId("source-indexing-copy")).toBeNull();
  });

  it("ofrece Indexar ahora si no hay job", async () => {
    const onIndex = vi.fn();
    const user = userEvent.setup();
    render(
      <MemoryRouter>
        <AgentSourcePicker
          sources={[EMPTY]}
          selectedIds={[]}
          jobs={[]}
          loading={false}
          onToggle={() => {}}
          onIndex={onIndex}
        />
      </MemoryRouter>,
    );
    await user.click(screen.getByTestId("source-index-s1"));
    expect(onIndex).toHaveBeenCalledWith("s1");
  });

  it("filtra por nombre", async () => {
    const user = userEvent.setup();
    render(
      <MemoryRouter>
        <AgentSourcePicker
          sources={[
            { ...READY, id: "s1", name: "Políticas RRHH" },
            { ...READY, id: "s2", name: "Inventario.xlsx" },
          ]}
          selectedIds={[]}
          jobs={[]}
          loading={false}
          onToggle={() => {}}
          onIndex={() => {}}
        />
      </MemoryRouter>,
    );
    await user.type(screen.getByRole("searchbox"), "inventario");
    expect(screen.getByText("Inventario.xlsx")).toBeInTheDocument();
    expect(screen.queryByText("Políticas RRHH")).toBeNull();
  });

  it("lista con scroll interno", () => {
    render(
      <MemoryRouter>
        <AgentSourcePicker
          sources={[READY]}
          selectedIds={[]}
          jobs={[]}
          loading={false}
          onToggle={() => {}}
          onIndex={() => {}}
        />
      </MemoryRouter>,
    );
    const list = screen.getByTestId("source-picker-list");
    expect(list.className).toMatch(/overflow-y-auto/);
    expect(list.className).toMatch(/max-h-/);
  });

  it("el tope bloquea el ítem 501", async () => {
    const user = userEvent.setup();
    const onToggle = vi.fn();
    const selectedIds = Array.from({ length: 500 }, (_, i) => `filled-${i}`);
    render(
      <MemoryRouter>
        <AgentSourcePicker
          sources={[READY]}
          selectedIds={selectedIds}
          jobs={[]}
          loading={false}
          onToggle={onToggle}
          onIndex={() => {}}
        />
      </MemoryRouter>,
    );
    await user.click(screen.getByRole("checkbox"));
    expect(onToggle).not.toHaveBeenCalled();
    expect(screen.getByText("Un agente admite como máximo 500 fuentes.")).toBeInTheDocument();
  });
});

describe("AgentTestChat", () => {
  it("avisa si las fuentes elegidas no están indexadas", () => {
    render(
      <AgentTestChat
        turns={[]}
        input=""
        status=""
        playing={false}
        inactive={false}
        sources={[EMPTY]}
        selectedIds={["s1"]}
        onInput={() => {}}
        onSubmit={(e) => e.preventDefault()}
      />,
    );
    expect(screen.getByTestId("chat-wait-index")).toHaveTextContent(/termine el indexado/);
  });

  it("click derecho en la respuesta abre Ver flujo con los pasos del agente", async () => {
    const user = userEvent.setup();
    render(
      <AgentTestChat
        turns={[
          { role: "user", text: "hola" },
          {
            role: "assistant",
            text: "respuesta",
            flow: {
              method: "agent",
              verdict: { decider: "Agente", route: "Herramientas" },
              steps: [
                {
                  name: "search_knowledge",
                  status: "ok",
                  ms: 120,
                  detail: "tool_call",
                  type: "tool_call",
                  tool: "search_knowledge",
                },
              ],
              timings: { total_ms: 900 },
            },
          },
        ]}
        input=""
        status=""
        playing={false}
        inactive={false}
        sources={[READY]}
        selectedIds={["s1"]}
        onInput={() => {}}
        onSubmit={(e) => e.preventDefault()}
        session={{ token: "t", organizationId: "org-1", companyName: "Acme" }}
      />,
    );
    fireEvent.contextMenu(screen.getByText("respuesta").closest("article")!);
    const item = await screen.findByRole("menuitem", { name: "Ver flujo" });
    await user.click(item);
    // La historia reemplaza la telemetría: la herramienta se nombra en lenguaje
    // humano y su nombre técnico sigue disponible al abrir la etapa.
    expect(await screen.findByText("Respuesta completada")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: /Reunió evidencia/ }));
    expect(await screen.findByText("Consultó el conocimiento")).toBeInTheDocument();
    expect(screen.getByText("search_knowledge")).toBeInTheDocument();
    expect(screen.getByText("900 ms")).toBeInTheDocument();
  });
});
