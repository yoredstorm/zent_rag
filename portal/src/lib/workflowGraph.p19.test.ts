import { describe, expect, it } from "vitest";
import { NODE_LIBRARY } from "./workflowGraph";

// P19-03: el canvas ya expone «Consultar registros». El editor real vive en
// NodeConfigPanel/DataQueryForm; aquí se protege la entrada de paleta y que el
// nodo no transporte SQL, tabla ni conexión.
describe("P19-03 — nodo visual Consultar registros", () => {
  it("existe data_query con etiqueta de negocio", () => {
    const node = NODE_LIBRARY.data_query;
    expect(node).toBeDefined();
    expect(node.label).toBe("Consultar registros");
    expect(node.category).toBe("data");
  });

  it("solo configura capability, binding y params", () => {
    const keys = NODE_LIBRARY.data_query.fields.map((field) => field.key);
    expect(keys).toEqual(["capability", "binding_ref", "params"]);
    expect(JSON.stringify(NODE_LIBRARY.data_query)).not.toMatch(/sql|connection_ref|columns/);
  });

  it("sigue existiendo la pregunta semántica separada", () => {
    expect(NODE_LIBRARY.query_business_data.fields.map((field) => field.key)).toEqual(["ask"]);
  });
});
