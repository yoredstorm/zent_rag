import { describe, expect, it } from "vitest";
import { sourceReadiness } from "./sourceState";

describe("sourceReadiness", () => {
  it("solo declara listo cuando el indexado terminó", () => {
    expect(sourceReadiness("indexed")).toMatchObject({
      key: "ready",
      label: "Listo para consultar",
    });
    for (const status of ["created", "connected", "discovering", "profiled", "ready", "ingesting"]) {
      expect(sourceReadiness(status).key).not.toBe("ready");
    }
  });

  it("distingue recibido, procesando, atención y no medido", () => {
    expect(sourceReadiness("created").key).toBe("received");
    expect(sourceReadiness("ingesting").key).toBe("processing");
    expect(sourceReadiness("error").key).toBe("attention");
    expect(sourceReadiness("desconocido")).toMatchObject({
      key: "unknown",
      label: "No medido",
    });
  });

  it("una base de datos conectada está lista aunque no tenga documentos", () => {
    expect(sourceReadiness("ready", "sql")).toMatchObject({
      key: "ready",
      label: "Base de datos conectada",
    });
    expect(sourceReadiness("error", "sql").key).toBe("attention");
  });
});
