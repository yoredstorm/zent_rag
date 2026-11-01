import { render, screen, waitFor, within } from "@testing-library/react";
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
function stubApi(
  steps: Record<string, unknown>[],
  runStatus = "succeeded",
  runOut: Record<string, unknown> = {},
  testSteps: Record<string, unknown>[] = [],
) {
  vi.stubGlobal(
    "fetch",
    vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      if (url.endsWith("/runs") && (init?.method ?? "GET") === "GET") {
        return Promise.resolve(json({ runs: [] }));
      }
      if (url.endsWith("/test")) {
        const body = init?.body ? JSON.parse(String(init.body)) : {};
        const requested = String(body.requested_level ?? "simulation");
        const preview = requested === "preview";
        const capped = requested === "sandbox" || requested === "provider";
        return Promise.resolve(
          json({
            requested_level: requested,
            effective_level: capped ? "simulation" : requested,
            capped_reason: capped ? "provider_adapter_unavailable" : null,
            provider_verified: false,
            result: preview ? "PREVIEW" : capped ? "UNVERIFIED" : "PASSED",
            executed_nodes: testSteps,
            timeline: [],
            hashes: { graph_hash: "g", plan_hash: "p", role_hash: "r", binding_hash: "b" },
          }),
        );
      }
      if (url.endsWith("/run")) {
        return Promise.resolve(
          json({ run_id: "r1", status: runStatus, planned_effects: [], ...runOut }),
        );
      }
      if (url.includes("/workflows/runs/r1")) {
        return Promise.resolve(json({ id: "r1", status: runStatus, steps }));
      }
      return Promise.resolve(json({}));
    }),
  );
}

function systemMessages(): string {
  return screen
    .queryAllByTestId("wf-chat-system")
    .map((element) => element.textContent ?? "")
    .join(" ");
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

async function confirmReal(user: ReturnType<typeof userEvent.setup>) {
  const dialog = await screen.findByRole("dialog", { name: "Ejecutar workflow con efectos reales" });
  await user.type(within(dialog).getByLabelText("Escribe EJECUTAR para confirmar"), "EJECUTAR");
  await user.click(within(dialog).getByRole("button", { name: "Ejecutar de verdad" }));
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("WorkflowTestPanel (dock de prueba)", () => {
  it("muestra la respuesta del agente como texto, no como JSON", async () => {
    const steps = [
      { step_index: 0, step_type: "llm", node_id: "ask", node_type: "llm", status: "succeeded", output: { text: "El gerente es Ana." } },
    ];
    stubApi(steps, "succeeded", {}, steps);
    const user = userEvent.setup();
    renderDock();

    await user.type(screen.getByTestId("wf-test-payload"), "quien es el gerente");
    expect(screen.getByTestId("wf-payload-wrapped")).toHaveTextContent(/"message":"quien es el gerente"/);

    await user.click(screen.getByTestId("wf-test"));
    await waitFor(() => expect(screen.getByTestId("wf-chat-answer")).toHaveTextContent("El gerente es Ana."));
    expect(screen.queryByText(/"simulated"/)).toBeNull();
  });

  it("avisa cuando la respuesta fue un eco por falta de agente", async () => {
    const steps = [
      { step_index: 0, step_type: "llm", node_id: "ask", node_type: "llm", status: "succeeded", output: { text: "[gpt-4o-mini] hola", echo: true } },
    ];
    stubApi(steps, "succeeded", {}, steps);
    const user = userEvent.setup();
    renderDock();

    await user.type(screen.getByTestId("wf-test-payload"), "hola");
    await user.click(screen.getByTestId("wf-test"));
    await waitFor(() => expect(screen.getByTestId("wf-chat-echo")).toBeInTheDocument());
  });

  it("muestra el error real del agente en vez de tragárselo", async () => {
    const steps = [
      { step_index: 0, step_type: "llm", node_id: "ask", node_type: "llm", status: "failed", output: {}, error: "el agente falló: limit_reached" },
    ];
    stubApi(steps, "failed", {}, steps);
    const user = userEvent.setup();
    renderDock();

    await user.type(screen.getByTestId("wf-test-payload"), "hola");
    await user.click(screen.getByTestId("wf-test"));
    await waitFor(() => expect(screen.getByText(/limit_reached/)).toBeInTheDocument());
  });

  it("el ejemplo de rol no pide JSON y el reporte no finge proveedor", async () => {
    stubApi([]);
    const user = userEvent.setup();
    renderDock();
    expect(screen.getByTestId("wf-level-preview")).toBeInTheDocument();
    expect(screen.getByTestId("wf-mode-real")).toBeInTheDocument();
    await user.click(screen.getByText("Escenario (opcional)"));
    await user.click(screen.getByTestId("wf-role-bienestar"));
    expect(screen.getByTestId("wf-test-payload")).toHaveValue("Dime qué enfermedad tengo");
    await user.click(screen.getByTestId("wf-test"));
    await waitFor(() => expect(systemMessages()).toContain("PASSED"));
  });

  it("el reporte persiste hashes y no declara PROVIDER_VERIFIED", async () => {
    stubApi([]);
    const user = userEvent.setup();
    renderDock();

    await user.type(screen.getByTestId("wf-test-payload"), "hola");
    await user.click(screen.getByTestId("wf-test"));
    await waitFor(() => expect(screen.getByTestId("wf-result-tab-verification")).toBeInTheDocument());
    await user.click(screen.getByTestId("wf-result-tab-verification"));
    await waitFor(() => expect(screen.getByTestId("wf-test-report")).toBeInTheDocument());
    expect(screen.getByTestId("wf-test-report")).toHaveTextContent("graph_hash: g");
    expect(systemMessages()).not.toContain("PROVIDER_VERIFIED");
  });

  it("sandbox y proveedor se degradan sin simular un pase", async () => {
    stubApi([]);
    const user = userEvent.setup();
    renderDock();

    await user.click(screen.getByTestId("wf-mode-real"));
    await user.click(screen.getByTestId("wf-level-provider"));
    await user.type(screen.getByTestId("wf-test-payload"), "hola");
    await user.click(screen.getByTestId("wf-test"));
    await waitFor(() => expect(systemMessages()).toContain("no está conectado"));
    expect(systemMessages()).toContain("no acredita proveedor real");
    await user.click(screen.getByTestId("wf-result-tab-verification"));
    await waitFor(() => expect(screen.getByTestId("wf-test-report")).toHaveTextContent("UNVERIFIED"));
  });

  it("preview no ejecuta el workflow", async () => {
    stubApi([]);
    const user = userEvent.setup();
    renderDock();

    await user.click(screen.getByTestId("wf-level-preview"));
    await user.click(screen.getByTestId("wf-test"));
    await waitFor(() =>
      expect(screen.getByTestId("wf-chat-system")).toHaveTextContent("Preview teórico"),
    );
    const calls = (globalThis.fetch as unknown as { mock: { calls: unknown[][] } }).mock.calls;
    expect(calls.some((c) => String(c[0]).endsWith("/run"))).toBe(false);
  });

  it.each(["sandbox", "provider"] as const)(
    "el nivel %s no simula un pase",
    async (level) => {
      stubApi([]);
      const user = userEvent.setup();
      renderDock();

      await user.click(screen.getByTestId("wf-mode-real"));
      await user.click(screen.getByTestId(`wf-level-${level}`));
      expect(screen.getByTestId("wf-level-unavailable")).toBeInTheDocument();
      await user.type(screen.getByTestId("wf-test-payload"), "hola");
      await user.click(screen.getByTestId("wf-test"));
      await waitFor(() =>
        expect(screen.getByTestId("wf-chat-system")).toHaveTextContent(/no está conectad/),
      );
      const calls = (globalThis.fetch as unknown as { mock: { calls: unknown[][] } }).mock.calls;
      expect(calls.some((c) => String(c[0]).endsWith("/run"))).toBe(false);
    },
  );

  it("los avisos del grafo llevan al nodo culpable", async () => {
    stubApi([]);
    const onSelectNode = vi.fn();
    const user = userEvent.setup();
    renderDock({
      issues: [{ node_id: "ask", label: "Preguntar a un agente", message: "Elige un agente" }],
      onSelectNode,
    });

    await user.click(screen.getByText("Preparación para probar"));
    await user.click(screen.getByTestId("wf-issue-jump"));
    expect(onSelectNode).toHaveBeenCalledWith("ask");
  });

  it("guarda el grafo antes de correr: el motor usa la versión persistida", async () => {
    const steps = [
      { step_index: 0, step_type: "llm", node_id: "ask", node_type: "llm", status: "succeeded", output: { text: "ok" } },
    ];
    stubApi(steps, "succeeded", {}, steps);
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
    await waitFor(() => expect(screen.getByTestId("wf-test-error")).toHaveTextContent("No pude guardar el grafo"));
    const calls = (globalThis.fetch as unknown as { mock: { calls: unknown[][] } }).mock.calls;
    expect(calls.some((c) => String(c[0]).endsWith("/test"))).toBe(false);
    expect(calls.some((c) => String(c[0]).endsWith("/run"))).toBe(false);
  });

  it("bloquea doble envío del mismo test", async () => {
    let resolveTest: ((value: Response) => void) | undefined;
    vi.stubGlobal(
      "fetch",
      vi.fn((input: RequestInfo | URL) => {
        const url = String(input);
        if (url.endsWith("/runs")) return Promise.resolve(json({ runs: [] }));
        if (url.endsWith("/test") && !resolveTest) {
          return new Promise<Response>((resolve) => {
            resolveTest = resolve;
          });
        }
        return Promise.resolve(json({}));
      }),
    );
    const user = userEvent.setup();
    renderDock();

    await user.type(screen.getByTestId("wf-test-payload"), "hola");
    try {
      await user.dblClick(screen.getByTestId("wf-test"));
      const calls = (globalThis.fetch as unknown as { mock: { calls: unknown[][] } }).mock.calls;
      expect(calls.filter((call) => String(call[0]).endsWith("/test"))).toHaveLength(1);
    } finally {
      resolveTest?.(
        json({
          requested_level: "simulation",
          effective_level: "simulation",
          provider_verified: false,
          result: "PASSED",
          executed_nodes: [],
          timeline: [],
        }),
      );
    }
    await waitFor(() => expect(screen.getByTestId("wf-result-headline")).toBeInTheDocument());
  });

  it("ignora un resultado tardío de otro workflow", async () => {
    let resolveTest: ((value: Response) => void) | undefined;
    vi.stubGlobal(
      "fetch",
      vi.fn((input: RequestInfo | URL) => {
        const url = String(input);
        if (url.endsWith("/runs")) return Promise.resolve(json({ runs: [] }));
        if (url.endsWith("/test")) {
          return new Promise<Response>((resolve) => {
            resolveTest = resolve;
          });
        }
        return Promise.resolve(json({}));
      }),
    );
    const user = userEvent.setup();
    const view = renderDock({ workflowId: "wf-1" });

    await user.type(screen.getByTestId("wf-test-payload"), "hola");
    await user.click(screen.getByTestId("wf-test"));

    view.rerender(
      <MemoryRouter>
        <WorkflowTestPanel
          workflowId="wf-2"
          status="draft"
          effectLabels={[]}
          issues={[]}
          dirty={false}
          onRun={() => undefined}
          onSelectNode={() => undefined}
        />
      </MemoryRouter>,
    );

    try {
      resolveTest?.(
        json({
          requested_level: "simulation",
          effective_level: "simulation",
          provider_verified: false,
          result: "PASSED",
          executed_nodes: [
            { node_id: "ask", node_type: "llm", status: "succeeded", output: { text: "viejo" } },
          ],
          timeline: [],
        }),
      );
      await new Promise((resolve) => setTimeout(resolve, 20));
      expect(screen.queryByTestId("wf-chat-answer")).toBeNull();
      expect(screen.queryByTestId("wf-result-headline")).toBeNull();
    } finally {
      resolveTest?.(json({}));
    }
  });

  it("ejecutar de verdad pide confirmación cuando hay nodos de escritura", async () => {
    stubApi([]);
    const user = userEvent.setup();
    renderDock({ effectLabels: ["Avisar al equipo"] });

    await user.type(screen.getByTestId("wf-test-payload"), "hola");
    await user.click(screen.getByTestId("wf-run"));
    const dialog = await screen.findByRole("dialog", { name: "Ejecutar workflow con efectos reales" });
    expect(dialog).toHaveTextContent("Avisar al equipo");
    expect(within(dialog).getByRole("button", { name: "Ejecutar de verdad" })).toBeDisabled();
  });

  it("caracteriza /test: nivel y escenario, sin llamar a /run", async () => {
    const testSteps = [
      { step_index: 0, step_type: "llm", node_id: "ask", node_type: "llm", status: "succeeded", output: { text: "ok" } },
    ];
    stubApi(testSteps, "succeeded", {}, testSteps);
    const user = userEvent.setup();
    renderDock();

    await user.type(screen.getByTestId("wf-test-payload"), "hola");
    await user.click(screen.getByTestId("wf-test"));
    await waitFor(() => expect(screen.getByTestId("wf-result-tab-path")).toBeInTheDocument());
    await user.click(screen.getByTestId("wf-result-tab-path"));
    await waitFor(() => expect(screen.getByTestId("wf-run-inspector")).toBeInTheDocument());

    const calls = (globalThis.fetch as unknown as { mock: { calls: unknown[][] } }).mock.calls;
    const testCall = calls.find((call) => String(call[0]).endsWith("/test"));
    expect(testCall).toBeTruthy();
    const body = JSON.parse(String((testCall?.[1] as RequestInit | undefined)?.body));
    expect(body.requested_level).toBe("simulation");
    expect(body.scenario.messages).toEqual(["hola"]);
    expect(calls.some((call) => String(call[0]).endsWith("/run"))).toBe(false);
  });

  it("Enter ejecuta simulación y Shift+Enter agrega línea sin ejecutar", async () => {
    const testSteps = [
      { step_index: 0, step_type: "llm", node_id: "ask", node_type: "llm", status: "succeeded", output: { text: "ok" } },
    ];
    stubApi(testSteps, "succeeded", {}, testSteps);
    const user = userEvent.setup();
    renderDock();

    const input = screen.getByTestId("wf-test-payload");
    await user.click(input);
    await user.keyboard("{Shift>}{Enter}{/Shift}");
    const callsAfterShift = (globalThis.fetch as unknown as { mock: { calls: unknown[][] } }).mock.calls;
    expect(callsAfterShift.some((call) => String(call[0]).endsWith("/test"))).toBe(false);

    await user.type(input, "hola{Enter}");
    await waitFor(() => expect(screen.getByTestId("wf-result-headline")).toBeInTheDocument());
    const calls = (globalThis.fetch as unknown as { mock: { calls: unknown[][] } }).mock.calls;
    expect(calls.filter((call) => String(call[0]).endsWith("/test"))).toHaveLength(1);
  });

  it("no ejecuta con Enter en modo real ni con input vacío", async () => {
    stubApi([]);
    const user = userEvent.setup();
    renderDock();

    expect(screen.getByTestId("wf-test")).toBeDisabled();
    await user.click(screen.getByTestId("wf-mode-real"));
    await user.click(screen.getByTestId("wf-level-provider"));
    await user.type(screen.getByTestId("wf-test-payload"), "hola{Enter}");
    const calls = (globalThis.fetch as unknown as { mock: { calls: unknown[][] } }).mock.calls;
    expect(calls.some((call) => String(call[0]).endsWith("/test"))).toBe(false);
  });

  it("Usar último conserva el payload y permite restaurar el borrador", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn((input: RequestInfo | URL) => {
        const url = String(input);
        if (url.endsWith("/runs")) return Promise.resolve(json({ runs: [] }));
        if (url.endsWith("/sample-outputs")) {
          return Promise.resolve(
            json({ run_id: "r1", trigger_payload: { message: "ultimo", order_id: "A-1" } }),
          );
        }
        return Promise.resolve(json({}));
      }),
    );
    const user = userEvent.setup();
    renderDock();

    await user.click(screen.getByText("Escenario (opcional)"));
    await user.click(screen.getByTestId("wf-sample-last"));
    await waitFor(() =>
      expect(screen.getByTestId("wf-test-payload")).toHaveValue(
        JSON.stringify({ message: "ultimo", order_id: "A-1" }, null, 2),
      ),
    );
    await user.click(screen.getByTestId("wf-restore-draft"));
    expect(screen.getByTestId("wf-test-payload")).toHaveValue("");
  });

  it("caracteriza /run real: payload normalizado y simulate false", async () => {
    stubApi([
      { step_index: 0, step_type: "llm", node_id: "ask", node_type: "llm", status: "succeeded", output: { text: "ok" } },
    ]);
    const user = userEvent.setup();
    renderDock();

    await user.type(screen.getByTestId("wf-test-payload"), "hola");
    await user.click(screen.getByTestId("wf-run"));
    await confirmReal(user);
    await waitFor(() => expect(screen.getByTestId("wf-chat-answer")).toHaveTextContent("ok"));

    const calls = (globalThis.fetch as unknown as { mock: { calls: unknown[][] } }).mock.calls;
    const runCall = calls.find((call) => String(call[0]).endsWith("/run"));
    const body = JSON.parse(String((runCall?.[1] as RequestInit | undefined)?.body));
    expect(body.payload).toEqual({ message: "hola", query: "hola" });
    expect(body.simulate).toBe(false);
  });

  it("acepta el run durable envuelto y muestra el resultado", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
        const url = String(input);
        if (url.endsWith("/runs") && (init?.method ?? "GET") === "GET") {
          return Promise.resolve(json({ runs: [] }));
        }
        if (url.endsWith("/run")) {
          return Promise.resolve(
            json({ status: "running", run: { run_id: "r1", status: "pending_approval" } }),
          );
        }
        if (url.includes("/workflows/runs/r1")) {
          return Promise.resolve(json({ id: "r1", status: "pending_approval", steps: [] }));
        }
        return Promise.resolve(json({}));
      }),
    );
    const user = userEvent.setup();
    renderDock();

    await user.type(screen.getByTestId("wf-test-payload"), "hola");
    await user.click(screen.getByTestId("wf-run"));
    await confirmReal(user);

    await waitFor(() => expect(screen.getByTestId("wf-result-headline")).toBeInTheDocument());
    const calls = (globalThis.fetch as unknown as { mock: { calls: unknown[][] } }).mock.calls;
    expect(calls.some((call) => String(call[0]).includes("/workflows/runs/r1"))).toBe(true);
  });

  it("caracteriza JSON: conserva el objeto completo y no lo envuelve", async () => {
    stubApi([]);
    const user = userEvent.setup();
    renderDock();

    const input = screen.getByTestId("wf-test-payload");
    await user.click(input);
    await user.paste('{"message":"hola","order_id":"A-1"}');
    expect(screen.queryByTestId("wf-payload-wrapped")).toBeNull();

    await user.click(screen.getByTestId("wf-run"));
    await confirmReal(user);
    await waitFor(() => expect(screen.getByTestId("wf-result-tab-path")).toBeInTheDocument());
    await user.click(screen.getByTestId("wf-result-tab-path"));
    await waitFor(() => expect(screen.getByTestId("wf-run-inspector")).toBeInTheDocument());

    const calls = (globalThis.fetch as unknown as { mock: { calls: unknown[][] } }).mock.calls;
    const runCall = calls.find((call) => String(call[0]).endsWith("/run"));
    const body = JSON.parse(String((runCall?.[1] as RequestInit | undefined)?.body));
    expect(body.payload).toEqual({ message: "hola", order_id: "A-1" });
  });

  it("guarda antes de probar también en el nivel de test", async () => {
    stubApi([]);
    const onSaveBeforeRun = vi.fn(async () => true);
    const user = userEvent.setup();
    renderDock({ dirty: true, onSaveBeforeRun });

    await user.type(screen.getByTestId("wf-test-payload"), "hola");
    await user.click(screen.getByTestId("wf-test"));
    await waitFor(() => expect(onSaveBeforeRun).toHaveBeenCalledTimes(1));
    const calls = (globalThis.fetch as unknown as { mock: { calls: unknown[][] } }).mock.calls;
    expect(calls.some((call) => String(call[0]).endsWith("/test"))).toBe(true);
  });

  it("cancelar la confirmación real no llama a /run", async () => {
    stubApi([]);
    const user = userEvent.setup();
    renderDock({ effectLabels: ["Avisar al equipo"] });

    await user.type(screen.getByTestId("wf-test-payload"), "hola");
    await user.click(screen.getByTestId("wf-run"));
    const dialog = await screen.findByRole("dialog", { name: "Ejecutar workflow con efectos reales" });
    await user.click(within(dialog).getByRole("button", { name: "Cancelar" }));
    const calls = (globalThis.fetch as unknown as { mock: { calls: unknown[][] } }).mock.calls;
    expect(calls.some((call) => String(call[0]).endsWith("/run"))).toBe(false);
  });

  it("sincroniza onRun y onSelectNode desde el resultado", async () => {
    const testSteps = [
      { step_index: 0, step_type: "llm", node_id: "ask", node_type: "llm", status: "succeeded", output: { text: "ok" } },
    ];
    stubApi(testSteps, "succeeded", {}, testSteps);
    const onRun = vi.fn();
    const onSelectNode = vi.fn();
    const user = userEvent.setup();
    renderDock({ onRun, onSelectNode });

    await user.type(screen.getByTestId("wf-test-payload"), "hola");
    await user.click(screen.getByTestId("wf-test"));
    await waitFor(() => expect(screen.getByTestId("wf-result-tab-path")).toBeInTheDocument());
    await user.click(screen.getByTestId("wf-result-tab-path"));
    await waitFor(() => expect(screen.getByTestId("wf-run-inspector")).toBeInTheDocument());
    expect(onRun).toHaveBeenCalledWith(
      expect.objectContaining({ steps: [expect.objectContaining({ node_id: "ask" })] }),
    );

    await user.click(screen.getByTestId("wf-step-jump"));
    expect(onSelectNode).toHaveBeenCalledWith("ask");
  });

  it("abre una corrida histórica sin cambiar el workflow", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn((input: RequestInfo | URL) => {
        const url = String(input);
        if (url.endsWith("/runs") && !url.endsWith("/workflows/runs/r1")) {
          return Promise.resolve(
            json({
              runs: [
                {
                  id: "r1",
                  workflow_id: "wf-1",
                  status: "succeeded",
                  started_at: "2026-10-30T00:00:00.000Z",
                  duration_ms: 42,
                  error: null,
                  simulate: true,
                },
              ],
            }),
          );
        }
        if (url.endsWith("/test")) {
          return Promise.resolve(
            json({
              requested_level: "simulation",
              effective_level: "simulation",
              provider_verified: false,
              result: "PASSED",
              executed_nodes: [],
              timeline: [],
            }),
          );
        }
        if (url.endsWith("/workflows/runs/r1")) {
          return Promise.resolve(json({ id: "r1", status: "succeeded", steps: [] }));
        }
        return Promise.resolve(json({}));
      }),
    );
    const user = userEvent.setup();
    renderDock();

    await user.type(screen.getByTestId("wf-test-payload"), "hola");
    await user.click(screen.getByTestId("wf-test"));
    await waitFor(() => expect(screen.getByText("Historial (1)")).toBeInTheDocument());
    await user.click(screen.getByText("Historial (1)"));
    await user.click(screen.getByTestId("wf-history-run"));
    await waitFor(() => expect(screen.getByTestId("wf-historical-result")).toBeInTheDocument());
  });

  it("notifica onRan después de una ejecución real", async () => {
    stubApi([
      { step_index: 0, step_type: "llm", node_id: "ask", node_type: "llm", status: "succeeded", output: { text: "ok" } },
    ]);
    const onRan = vi.fn();
    const user = userEvent.setup();
    renderDock({ onRan });

    await user.type(screen.getByTestId("wf-test-payload"), "hola");
    await user.click(screen.getByTestId("wf-run"));
    await confirmReal(user);
    await waitFor(() => expect(screen.getByTestId("wf-chat-answer")).toHaveTextContent("ok"));
    expect(onRan).toHaveBeenCalledTimes(1);
  });
});
