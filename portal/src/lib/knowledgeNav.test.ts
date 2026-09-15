import { describe, expect, it } from "vitest";
import {
  KNOWLEDGE_ADVANCED_TABS,
  KNOWLEDGE_HEADINGS,
  KNOWLEDGE_PILLARS,
  KNOWLEDGE_ROUTE_TITLES,
  KNOWLEDGE_SUBNAVS,
  knowledgePillarForPath,
} from "./knowledgeNav";

describe("knowledge IA", () => {
  it("expone 3 pilares y no más de 6 pestañas primarias (pilares + Avanzado)", () => {
    expect(KNOWLEDGE_PILLARS.map((tab) => tab.label)).toEqual([
      "Resumen",
      "Fuentes",
      "Aprendizaje",
    ]);
    const visibleWithoutAdvanced = KNOWLEDGE_PILLARS.length + 1;
    expect(visibleWithoutAdvanced).toBeLessThanOrEqual(6);
  });

  it("no pone Semántica ni Términos en el rail primario", () => {
    const primaryLabels = KNOWLEDGE_PILLARS.map((tab) => tab.label);
    expect(primaryLabels).not.toContain("Semántica");
    expect(primaryLabels).not.toContain("Términos");
    expect(primaryLabels).not.toContain("Mejora");
    expect(KNOWLEDGE_SUBNAVS.mejora.map((tab) => tab.label)).toEqual(["Aprendizaje", "Mapa"]);
    expect(KNOWLEDGE_SUBNAVS).not.toHaveProperty("fuentes");
    expect(KNOWLEDGE_SUBNAVS).not.toHaveProperty("semantica");
  });

  it("mantiene herramientas avanzadas fuera del rail visible", () => {
    expect(KNOWLEDGE_ADVANCED_TABS.map((tab) => tab.to)).toEqual([
      "/knowledge/glossary",
      "/knowledge/catalog",
      "/connectors",
      "/knowledge/jobs",
    ]);
    expect(KNOWLEDGE_ADVANCED_TABS.map((tab) => tab.label)).toEqual([
      "Términos",
      "Catálogo",
      "Conectores",
      "Trabajos",
    ]);
  });

  it("resuelve el pilar activo por ruta", () => {
    expect(knowledgePillarForPath("/knowledge")).toBe("resumen");
    expect(knowledgePillarForPath("/knowledge/")).toBe("resumen");
    expect(knowledgePillarForPath("/knowledge/workspaces")).toBe("avanzado");
    expect(knowledgePillarForPath("/knowledge/sources")).toBe("fuentes");
    expect(knowledgePillarForPath("/knowledge/sources/abc")).toBe("fuentes");
    expect(knowledgePillarForPath("/knowledge/add")).toBe("fuentes");
    expect(knowledgePillarForPath("/knowledge/glossary")).toBe("avanzado");
    expect(knowledgePillarForPath("/knowledge/catalog")).toBe("avanzado");
    expect(knowledgePillarForPath("/knowledge/understanding")).toBe("avanzado");
    expect(knowledgePillarForPath("/knowledge/learning")).toBe("mejora");
    expect(knowledgePillarForPath("/knowledge/map")).toBe("mejora");
    expect(knowledgePillarForPath("/knowledge/jobs")).toBe("avanzado");
    expect(knowledgePillarForPath("/connectors")).toBe("avanzado");
  });

  it("usa headings de página únicos y estables", () => {
    const titles = Object.values(KNOWLEDGE_HEADINGS);
    expect(new Set(titles).size).toBe(titles.length);
    expect(KNOWLEDGE_HEADINGS.overview).toBe("Resumen");
    expect(KNOWLEDGE_HEADINGS.sources).toBe("Fuentes");
    expect(KNOWLEDGE_HEADINGS.learning).toBe("Aprendizaje");
    expect(KNOWLEDGE_ROUTE_TITLES["/knowledge"]).toBe(KNOWLEDGE_HEADINGS.overview);
    expect(KNOWLEDGE_ROUTE_TITLES["/knowledge/sources"]).toBe(KNOWLEDGE_HEADINGS.sources);
  });
});
