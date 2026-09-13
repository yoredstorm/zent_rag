import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState } from "react";
import { describe, expect, it, vi } from "vitest";
import type { BusinessParameter } from "../../lib/businessSchema";
import { BusinessParameterForm } from "./BusinessParameterForm";

function param(partial: Partial<BusinessParameter> & { key: string; label: string }): BusinessParameter {
  return {
    type: "text",
    required: false,
    default: undefined,
    placeholder: null,
    examples: [],
    advanced: false,
    min_level: "simple",
    secret: false,
    dynamic_options: null,
    data_source: null,
    unit: null,
    validation: {},
    help: null,
    business_group: null,
    ...partial,
  };
}

const PARAMS: BusinessParameter[] = [
  param({ key: "channel", label: "Enviar por", type: "enum", required: true, validation: { options: [{ value: "in_app", label: "Zent" }, { value: "email", label: "Correo" }] } }),
  param({ key: "message", label: "Mensaje", type: "textarea", data_source: "any" }),
  param({ key: "data", label: "Datos adjuntos (JSON)", type: "json", advanced: true, min_level: "advanced" }),
  param({ key: "smtp_password", label: "Password SMTP", type: "secret", secret: true }),
  param({ key: "count", label: "Cantidad", type: "number" }),
];

const REFS = [{ value: "{{nodes.n1.output.total}}", label: "Consulta de ventas → Total" }];

function renderForm(level: "simple" | "guided" | "advanced", onChange = vi.fn()) {
  function Harness() {
    const [values, setValues] = useState<Record<string, unknown>>({});
    return (
      <BusinessParameterForm
        parameters={PARAMS}
        level={level}
        values={values}
        onChange={(key, value, p) => {
          setValues((prev) => ({ ...prev, [key]: value }));
          onChange(key, value, p);
        }}
        referenceOptions={REFS}
      />
    );
  }
  render(<Harness />);
  return onChange;
}

describe("BusinessParameterForm", () => {
  it("Simple oculta avanzados y secretos; Advanced los muestra", () => {
    renderForm("simple");
    expect(screen.getByTestId("wf-param-channel")).toBeInTheDocument();
    expect(screen.queryByTestId("wf-param-data")).toBeNull();
    expect(screen.queryByTestId("wf-param-smtp_password")).toBeNull();
  });

  it("Advanced muestra campos avanzados pero no secretos por defecto", () => {
    renderForm("advanced");
    expect(screen.getByTestId("wf-param-data")).toBeInTheDocument();
    expect(screen.queryByTestId("wf-param-smtp_password")).toBeNull();
  });

  it("un enum escribe el valor de negocio, no la etiqueta", async () => {
    const user = userEvent.setup();
    const onChange = renderForm("simple");
    await user.selectOptions(screen.getByTestId("wf-param-channel"), "email");
    expect(onChange).toHaveBeenCalledWith("channel", "email", expect.objectContaining({ key: "channel" }));
  });

  it("los números se escriben como número", async () => {
    const user = userEvent.setup();
    const onChange = renderForm("simple");
    await user.type(screen.getByTestId("wf-param-count"), "10");
    const last = onChange.mock.calls[onChange.mock.calls.length - 1];
    expect(last[0]).toBe("count");
    expect(last[1]).toBe(10);
  });

  it("el selector de datos inserta la referencia con su etiqueta de negocio", async () => {
    const user = userEvent.setup();
    const onChange = renderForm("simple");
    await user.click(screen.getByTestId("wf-param-message-refs"));
    await user.click(screen.getByText("Consulta de ventas → Total"));
    expect(onChange).toHaveBeenCalledWith("message", "{{nodes.n1.output.total}}", expect.objectContaining({ key: "message" }));
  });
});
