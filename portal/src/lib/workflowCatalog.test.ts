import { beforeEach, describe, expect, it, vi } from "vitest";
import { NODE_LIBRARY } from "./workflowGraph";
import {
  catalogIndex,
  catalogNodeToMeta,
  clearNodeCatalogCache,
  fetchNodeCatalog,
  libraryWithCatalog,
  parameterToField,
  type NodeCatalogPayload,
} from "./workflowCatalog";

const PAYLOAD: NodeCatalogPayload = {
  catalog_version: 1,
  generated_at: "2026-09-14T00:00:00Z",
  categories: [{ id: "data", label: "Datos", order: 1 }],
  nodes: [
    {
      node_type: "query_business_data",
      version: 1,
      label: "Consultar datos de negocio",
      business_name: "Pregunta a tus datos",
      short_description: "Pregunta en lenguaje natural.",
      category: "data",
      risk_level: "normal",
      inputs: { in: { type: "json" } },
      outputs: { out: { type: "record_list" } },
      context_reads: ["trigger", "variables"],
      context_writes: ["data", "evidence"],
      requires: ["managed_db"],
      parameters: [
        { key: "ask", label: "¿Qué dato necesitas?", type: "textarea", required: true, data_source: "any" },
        { key: "limit", label: "Máximo", type: "integer", min_level: "guided" },
      ],
      available: false,
      unavailable_reason: "No hay una base de datos de negocio conectada.",
    },
  ],
};

describe("workflowCatalog — normalización backend → NodeMeta", () => {
  it("mapea nombre de negocio, puertos, contexto y disponibilidad", () => {
    const meta = catalogNodeToMeta(PAYLOAD.nodes[0]);
    expect(meta.type).toBe("query_business_data");
    expect(meta.label).toBe("Pregunta a tus datos");
    expect(meta.category).toBe("data");
    expect(meta.ports?.input).toEqual([{ name: "in", type: "json" }]);
    expect(meta.ports?.output).toEqual([{ name: "out", type: "record_list" }]);
    expect(meta.contextReads).toEqual(["trigger", "variables"]);
    expect(meta.contextWrites).toEqual(["data", "evidence"]);
    expect(meta.requires).toEqual(["managed_db"]);
    expect(meta.available).toBe(false);
    expect(meta.unavailableReason).toBe("No hay una base de datos de negocio conectada.");
    expect(meta.description).toBe("Pregunta en lenguaje natural.");
    // Tipos visuales conservados del registry local.
    expect(meta.icon).toBe(NODE_LIBRARY.query_business_data.icon);
    expect(meta.color).toBe(NODE_LIBRARY.query_business_data.color);
  });

  it("convierte parámetros del backend a campos legacy", () => {
    const meta = catalogNodeToMeta(PAYLOAD.nodes[0]);
    const ask = meta.fields.find((f) => f.key === "ask");
    const limit = meta.fields.find((f) => f.key === "limit");
    expect(ask?.type).toBe("textarea");
    expect(ask?.refs).toBe(true);
    expect(limit?.type).toBe("number");
    expect(limit?.adv).toBe(false);
  });

  it("conserva el fallback local para tipos ausentes del payload", () => {
    const library = libraryWithCatalog(PAYLOAD);
    expect(library.llm).toBe(NODE_LIBRARY.llm);
    expect(library.query_business_data.label).toBe("Pregunta a tus datos");
    expect(catalogIndex(null)).toEqual({});
    expect(libraryWithCatalog(null)).toEqual(NODE_LIBRARY);
  });

  it("parameterToField mapea enum y boolean", () => {
    expect(
      parameterToField({
        key: "channel",
        label: "Canal",
        type: "enum",
        validation: { options: [{ value: "in_app", label: "Zent" }] },
      }).options
    ).toEqual([{ value: "in_app", label: "Zent" }]);
    expect(parameterToField({ key: "flag", label: "Activo", type: "boolean" }).options).toEqual([
      { value: "true", label: "Sí" },
      { value: "false", label: "No" },
    ]);
  });
});

describe("workflowCatalog — fetch con caché y fallback", () => {
  beforeEach(() => {
    clearNodeCatalogCache();
  });

  it("cachea por key y devuelve null si falla", async () => {
    const fetcher = vi.fn().mockResolvedValue(PAYLOAD);
    const first = await fetchNodeCatalog(fetcher, "org-1");
    const second = await fetchNodeCatalog(fetcher, "org-1");
    expect(first).toBe(PAYLOAD);
    expect(second).toBe(PAYLOAD);
    expect(fetcher).toHaveBeenCalledTimes(1);

    clearNodeCatalogCache();
    const failing = vi.fn().mockRejectedValue(new Error("boom"));
    expect(await fetchNodeCatalog(failing, "org-1")).toBeNull();
  });

  it("payload sin nodes devuelve null", async () => {
    const fetcher = vi
      .fn()
      .mockResolvedValue({ catalog_version: 1, generated_at: "", categories: [] });
    expect(await fetchNodeCatalog(fetcher, "org-x")).toBeNull();
  });

  it("cambia de key cuando cambia el tenant", async () => {
    const fetcher = vi.fn().mockResolvedValue(PAYLOAD);
    await fetchNodeCatalog(fetcher, "org-1");
    await fetchNodeCatalog(fetcher, "org-2");
    expect(fetcher).toHaveBeenCalledTimes(2);
  });
});
