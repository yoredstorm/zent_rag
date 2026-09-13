import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";
import { WorkflowTestPanel } from "./WorkflowTestPanel";

// Identidad estable: `useAuth` es un contexto en la app y el dock recarga los
// runs cuando cambia la sesión; devolver un objeto nuevo por render lo cicla.
const AUTH = vi.hoisted(() => ({
  session: { token: "rag_sess_t", organizationId: "org-1", roles: ["owner"], permissions: [] },
}));

vi.mock("../../auth", () => ({ useAuth: () => AUTH }));

function json(body: unknown) {
  return new Response(JSON.stringify(body), {
    status: 200,
    headers: { "Content-Type": "application/json" },
  });
}

/** Backend mínimo: lista de runs, POST run y detalle del run. */
function stubApi(steps: Record<string, unknown>[], runStatus = "succeeded") {
  vi.stubGlobal(
    "fetch",
    vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      if (url.endsWith("/runs") && (init?.method ?? "GET") === "GET") {
        return Promise.resolve(json({ runs: [] }));
      }
      if (url.endsWith("/run")) {
        return Promise.resolve(json({ run_id: "r1", status: runStatus, planned_effects: [] }));
      }
      if (url.includes("/workflows/runs/r1")) {
        return Promise.resolve(json({ id: "r1", status: runStatus, steps }));
      }
      return Promise.resolve(json({}));
    }),
  );
}

function renderDock(extra: Partial<Parameters<typeof WorkflowTestPanel>[0]> = {}) {
  return render(
    <MemoryRouter>
      <WorkflowTestPanel
        workflowId="wf-1"
        status="draft"
        effectLabels={[]}
        issues={[]}
        dirty={false}
        onRun={() => undefined}
        onSelectNode={() => undefined}
        {...extra}
      />
    </MemoryRouter>,
  );
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("WorkflowTestPanel (dock de prueba)", () => {
  it("muestra la respuesta del agente como texto, no como JSON", async () => {
    stubApi([
      { step_index: 0, step_type: "llm", node_id: "ask", node_type: "llm", status: "succeeded", output: { text: "El gerente es Ana." } },
    ]);
    const user = userEvent.setup();
    renderDock();

    await user.type(screen.getByTestId("wf-test-payload"), "quien es el gerente");
    expect(screen.getByTestId("wf-payload-wrapped")).toHaveTextContent(/"message":"quien es el gerente"/);

    await user.click(screen.getByTestId("wf-test"));
    await waitFor(() => expect(screen.getByTestId("wf-chat-answer")).toHaveTextContent("El gerente es Ana."));
    expect(screen.getByTestId("wf-chat-user")).toHaveTextContent("quien es el gerente");
    expect(screen.queryByText(/"simulated"/)).toBeNull();
  });

  it("avisa cuando la respuesta fue un eco por falta de agente", async () => {
    stubApi([
      { step_index: 0, step_type: "llm", node_id: "ask", node_type: "llm", status: "succeeded", output: { text: "[gpt-4o-mini] hola", echo: true } },
    ]);
    const user = userEvent.setup();
    renderDock();

    await user.type(screen.getByTestId("wf-test-payload"), "hola");
    await user.click(screen.getByTestId("wf-test"));
    await waitFor(() => expect(screen.getByTestId("wf-chat-echo")).toBeInTheDocument());
  });

  it("muestra el error real del agente en vez de tragárselo", async () => {
    stubApi(
      [
        { step_index: 0, step_type: "llm", node_id: "ask", node_type: "llm", status: "failed", output: {}, error: "el agente falló: limit_reached" },
      ],
      "failed",
    );
    const user = userEvent.setup();
    renderDock();

    await user.type(screen.getByTestId("wf-test-payload"), "hola");
    await user.click(screen.getByTestId("wf-test"));
    await waitFor(() =>
      expect(screen.getByTestId("wf-chat-system")).toHaveTextContent("limit_reached"),
    );
  });

  it("los avisos del grafo llevan al nodo culpable", async () => {
    stubApi([]);
    const onSelectNode = vi.fn();
    const user = userEvent.setup();
    renderDock({
      issues: [{ node_id: "ask", label: "Preguntar a un agente", message: "Elige un agente" }],
      onSelectNode,
    });

    await user.click(screen.getByTestId("wf-issue-jump"));
    expect(onSelectNode).toHaveBeenCalledWith("ask");
  });

  it("guarda el grafo antes de correr: el motor usa la versión persistida", async () => {
    stubApi([
      { step_index: 0, step_type: "llm", node_id: "ask", node_type: "llm", status: "succeeded", output: { text: "ok" } },
    ]);
    const onSaveBeforeRun = vi.fn(async () => true);
    const user = userEvent.setup();
    renderDock({ dirty: true, onSaveBeforeRun });

    await user.type(screen.getByTestId("wf-test-payload"), "hola");
    await user.click(screen.getByTestId("wf-test"));
    await waitFor(() => expect(screen.getByTestId("wf-chat-answer")).toHaveTextContent("ok"));
    expect(onSaveBeforeRun).toHaveBeenCalledTimes(1);
  });

  it("no ejecuta si el guardado previo falla", async () => {
    stubApi([]);
    const onSaveBeforeRun = vi.fn(async () => false);
    const user = userEvent.setup();
    renderDock({ dirty: true, onSaveBeforeRun });

    await user.type(screen.getByTestId("wf-test-payload"), "hola");
    await user.click(screen.getByTestId("wf-test"));
    await waitFor(() =>
      expect(screen.getByTestId("wf-chat-system")).toHaveTextContent("No pude guardar el grafo"),
    );
    const calls = (globalThis.fetch as unknown as { mock: { calls: unknown[][] } }).mock.calls;
    expect(calls.some((c) => String(c[0]).endsWith("/run"))).toBe(false);
  });

  it("ejecutar de verdad pide confirmación cuando hay nodos de escritura", async () => {
    stubApi([]);
    const confirm = vi.fn(() => false);
    vi.stubGlobal("confirm", confirm);
    const user = userEvent.setup();
    renderDock({ effectLabels: ["Avisar al equipo"] });

    await user.click(screen.getByTestId("wf-run"));
    expect(confirm).toHaveBeenCalledWith(expect.stringContaining("Avisar al equipo"));
  });
});
