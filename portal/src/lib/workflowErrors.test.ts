import { describe, expect, it } from "vitest";
import { humanizeWorkflowError } from "./workflowErrors";

describe("humanizeWorkflowError", () => {
  it("traduce permisos a lenguaje de negocio", () => {
    expect(humanizeWorkflowError("permiso insuficiente: agents:execute")).toContain("permiso");
    expect(humanizeWorkflowError("permiso insuficiente: agents:execute")).toContain("administrador");
  });

  it("traduce agentes y nodos desconocidos", () => {
    expect(
      humanizeWorkflowError("El agente 11111111-1111-1111-1111-111111111111 no está disponible para este workflow: no existe"),
    ).toContain("Elige otro agente");
    expect(humanizeWorkflowError("tipo de nodo desconocido: mega_node")).toContain("Avanzado");
  });

  it("traduce integraciones y APIs bloqueadas", () => {
    expect(humanizeWorkflowError("integration missing")).toContain("conectar");
    expect(humanizeWorkflowError("call_api blocked: no api_allowlist configured for tenant")).toContain("bloqueada");
    expect(humanizeWorkflowError("Host 'foo.com' not in tenant api_allowlist")).toContain("foo.com");
  });

  it("traduce referencias inválidas", () => {
    expect(humanizeWorkflowError("invalid reference nodes.n4.output.stock")).toContain("No encontramos");
  });

  it("mantiene los mensajes ya humanos y vacíos", () => {
    expect(humanizeWorkflowError("Falta elegir a quién avisar.")).toBe("Falta elegir a quién avisar.");
    expect(humanizeWorkflowError("")).toBe("");
    expect(humanizeWorkflowError(null)).toBe("");
  });
});
