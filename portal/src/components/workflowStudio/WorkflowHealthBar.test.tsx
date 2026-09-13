import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { WorkflowHealthBar } from "./WorkflowHealthBar";

const AUTH = vi.hoisted(() => ({
  session: { token: "rag_sess_t", organizationId: "org-1", roles: ["owner"], permissions: [] },
}));

vi.mock("../../auth", () => ({ useAuth: () => AUTH }));

function json(body: unknown) {
  return new Response(JSON.stringify(body), { status: 200, headers: { "Content-Type": "application/json" } });
}

function stubApi(readiness: unknown) {
  vi.stubGlobal(
    "fetch",
    vi.fn((input: RequestInfo | URL) => {
      const url = String(input);
      if (url.includes("/summary")) {
        return Promise.resolve(
          json({ text: "Cuando ocurra inventory.updated, si Stock es menor que 10, Zent avisará por correo.", when: "", steps: [] }),
        );
      }
      if (url.includes("/readiness")) return Promise.resolve(json(readiness));
      return Promise.resolve(json({}));
    }),
  );
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("WorkflowHealthBar", () => {
  it("muestra el resumen y los problemas con lenguaje de negocio", async () => {
    stubApi({
      ready: false,
      errors: 1,
      warnings: 1,
      checks: [
        { key: "trigger", label: "Inicio del flujo", status: "ok", message: "ok" },
        { key: "outputs", label: "Salidas", status: "warning", message: "Falta elegir a quién avisar.", hint: null },
        { key: "agents", label: "Agentes", status: "error", message: "Falta elegir el agente.", hint: "Elige un agente activo." },
      ],
    });
    const user = userEvent.setup();
    render(<WorkflowHealthBar workflowId="wf-1" />);
    await waitFor(() => expect(screen.getByTestId("wf-summary-text")).toHaveTextContent("avisará por correo"));
    expect(screen.getByTestId("wf-check-outputs")).toBeInTheDocument();
    expect(screen.getByTestId("wf-readiness-toggle")).toHaveTextContent("1 por resolver");

    await user.click(screen.getByTestId("wf-readiness-toggle"));
    expect(screen.getByTestId("wf-readiness-list")).toHaveTextContent("Falta elegir a quién avisar.");
    expect(screen.getByTestId("wf-readiness-list")).toHaveTextContent("Falta elegir el agente.");
  });

  it("celebra cuando todo está listo", async () => {
    stubApi({
      ready: true,
      errors: 0,
      warnings: 0,
      checks: [{ key: "trigger", label: "Inicio del flujo", status: "ok", message: "ok" }],
    });
    render(<WorkflowHealthBar workflowId="wf-1" />);
    await waitFor(() => expect(screen.getByTestId("wf-readiness-ready")).toHaveTextContent("Listo para publicar"));
  });
});
