import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { api } from "../../api";
import { AgentPurposeForm } from "./AgentPurposeForm";
import { describeWarnings } from "./purposeWarnings";

vi.mock("../../api", () => ({ api: vi.fn() }));

function renderForm() {
  const onPurpose = vi.fn();
  render(
    <AgentPurposeForm
      name="Soporte"
      purpose=""
      instructions=""
      onName={() => {}}
      onPurpose={onPurpose}
      onInstructions={() => {}}
      agentId="a1"
      token="t"
      organizationId="o1"
    />,
  );
  return onPurpose;
}

async function generate() {
  const user = userEvent.setup();
  await user.click(screen.getByRole("button", { name: "Generar propósito con IA" }));
}

describe("AgentPurposeForm", () => {
  beforeEach(() => {
    vi.mocked(api).mockReset();
  });

  it("no auto-aplica: muestra la propuesta y aplica al confirmar", async () => {
    vi.mocked(api).mockResolvedValue({
      draft: "Atender las consultas sobre Soporte.",
      purpose: "Atender las consultas sobre Soporte.",
      additional_instructions: "Responde con claridad.",
      warnings: ["mentions_unconfigured_capability:api"],
      source: "rules",
      quality: { passed: false, issues: ["capability_grounding"] },
    });
    const onPurpose = renderForm();

    await generate();

    expect(onPurpose).not.toHaveBeenCalled();
    expect(screen.getByTestId("purpose-proposal")).toHaveTextContent(
      "capacidades no configuradas",
    );
    await userEvent.setup().click(screen.getByRole("button", { name: "Aplicar propósito" }));
    expect(onPurpose).toHaveBeenCalledWith("Atender las consultas sobre Soporte.");
  });

  it("sin fallos: propuesta lista sin guardar", async () => {
    vi.mocked(api).mockResolvedValue({
      draft: "Explicar tarifas con evidencia.",
      purpose: "Explicar tarifas con evidencia.",
      additional_instructions: "Cita la fuente.",
      warnings: [],
      source: "model",
      quality: { passed: true, issues: [] },
    });
    renderForm();

    await generate();

    const notice = screen.getByRole("status");
    expect(notice).toHaveTextContent("Propuesta lista para revisar");
    expect(notice.textContent).toContain("No se guardó nada");
    expect(notice.className).toContain("text-ok");
  });

  it("un fallo real se muestra y no toca el propósito", async () => {
    vi.mocked(api).mockRejectedValue(new Error("HTTP_503 No se pudo generar el propósito"));
    const onPurpose = renderForm();

    await generate();

    expect(onPurpose).not.toHaveBeenCalled();
    expect(screen.getByRole("alert")).toHaveTextContent("HTTP_503");
  });
});

describe("describeWarnings", () => {
  it("traduce los códigos del generador y conserva lo desconocido", () => {
    expect(describeWarnings(["mentions_unconfigured_capability:sql,api"])).toBe(
      "Se quitó una frase que mencionaba capacidades no configuradas (sql, api).",
    );
    expect(describeWarnings(["empty_model_output"])).toBe(
      "El modelo no devolvió texto: se propuso un borrador por reglas.",
    );
    expect(describeWarnings(["otro_aviso"])).toBe("otro_aviso");
  });
});
