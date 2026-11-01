import { describe, expect, it } from "vitest";
import { NODE_LIBRARY } from "./workflowGraph";

// P19-00: fotografía del lienzo actual. No es una prueba de aceptación:
// demuestra que hoy no existe un nodo visual «Consultar registros» ni
// selectores de conexión, recurso, columnas o preview. P19-03 debe cambiar
// estas expectativas (el test se actualizará con el nodo nuevo).
describe("P19-00 AS-IS — configuración de consultas en el canvas", () => {
  it("no existe un nodo visual de consulta por registros", () => {
    expect(NODE_LIBRARY.data_query).toBeUndefined();
    expect(NODE_LIBRARY.consultar_registros).toBeUndefined();
  });

  it("la única consulta de datos es una pregunta en texto libre", () => {
    const node = NODE_LIBRARY.query_business_data;
    expect(node.fields.map((field) => field.key)).toEqual(["ask"]);
    expect(node.fields[0].type).toBe("textarea");
  });

  it("el canvas no ofrece catálogo de conexiones ni recursos", () => {
    const serialized = JSON.stringify(NODE_LIBRARY.query_business_data);
    for (const missingSelector of ["connection_ref", "resource", "columns", "preview"]) {
      expect(serialized.includes(missingSelector)).toBe(false);
    }
  });
});
