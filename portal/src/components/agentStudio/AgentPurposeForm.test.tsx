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

  it("aplica el borrador por reglas y avisa el recorte", async () => {
    vi.mocked(api).mockResolvedValue({
      draft: "Atender las consultas sobre Soporte.",
      warnings: ["mentions_unconfigured_capability:api", "purpose_replaced_by_rules"],
      source: "rules",
    });
    const onPurpose = renderForm();

    await generate();

    expect(onPurpose).toHaveBeenCalledWith("Atender las consultas sobre Soporte.");
    const notice = screen.getByRole("status");
    expect(notice).toHaveTextContent("capacidades no configuradas (api)");
    expect(notice.className).toContain("text-warn");
  });

  it("sin recortes: avisa en tono ok", async () => {
    vi.mocked(api).mockResolvedValue({
      draft: "Explicar tarifas con evidencia.",
      warnings: [],
      source: "model",
    });
    renderForm();

    await generate();

    const notice = screen.getByRole("status");
    expect(notice).toHaveTextContent("Borrador generado");
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
