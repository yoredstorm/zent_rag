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
  it("expone 4 pilares y no más de 6 pestañas primarias (pilares + Avanzado)", () => {
    expect(KNOWLEDGE_PILLARS.map((tab) => tab.label)).toEqual([
      "Resumen",
      "Fuentes",
      "Semántica",
      "Mejora",
    ]);
    const visibleWithoutAdvanced = KNOWLEDGE_PILLARS.length + 1; // + botón Avanzado
    expect(visibleWithoutAdvanced).toBeLessThanOrEqual(6);
  });

  it("agrupa semántica y mejora en sub-navegación, no en el rail primario", () => {
    const primaryLabels = KNOWLEDGE_PILLARS.map((tab) => tab.label);
    expect(primaryLabels).not.toContain("Términos");
    expect(primaryLabels).not.toContain("Aprendizaje");
    expect(primaryLabels).not.toContain("Entendimiento");
    expect(KNOWLEDGE_SUBNAVS.semantica.map((tab) => tab.label)).toEqual([
      "Términos",
      "Catálogo",
      "Entendimiento",
    ]);
    expect(KNOWLEDGE_SUBNAVS.mejora.map((tab) => tab.label)).toEqual([
      "Aprendizaje",
      "Mapa",
      "Revisión",
      "Mejoras",
    ]);
    expect(KNOWLEDGE_SUBNAVS.fuentes.map((tab) => tab.to)).toEqual([
      "/knowledge/sources",
      "/knowledge/database",
      "/knowledge/sql",
      "/knowledge/collections",
      "/knowledge/documents",
    ]);
  });

  it("mantiene herramientas avanzadas fuera del rail visible", () => {
    expect(KNOWLEDGE_ADVANCED_TABS.map((tab) => tab.to)).toEqual([
      "/knowledge/jobs",
      "/knowledge/playground",
      "/knowledge-hub",
      "/connectors",
    ]);
  });

  it("resuelve el pilar activo por ruta", () => {
    expect(knowledgePillarForPath("/knowledge")).toBe("resumen");
    expect(knowledgePillarForPath("/knowledge/")).toBe("resumen");
    expect(knowledgePillarForPath("/knowledge/sources")).toBe("fuentes");
    expect(knowledgePillarForPath("/knowledge/sources/abc")).toBe("fuentes");
    expect(knowledgePillarForPath("/knowledge/add")).toBe("fuentes");
    expect(knowledgePillarForPath("/knowledge/database/import")).toBe("fuentes");
    expect(knowledgePillarForPath("/knowledge/glossary")).toBe("semantica");
    expect(knowledgePillarForPath("/knowledge/catalog")).toBe("semantica");
    expect(knowledgePillarForPath("/knowledge/understanding")).toBe("semantica");
    expect(knowledgePillarForPath("/knowledge/learning")).toBe("mejora");
    expect(knowledgePillarForPath("/knowledge/map")).toBe("mejora");
    expect(knowledgePillarForPath("/knowledge/review")).toBe("mejora");
    expect(knowledgePillarForPath("/knowledge/improvements")).toBe("mejora");
    expect(knowledgePillarForPath("/knowledge/jobs")).toBe("avanzado");
    expect(knowledgePillarForPath("/knowledge/playground")).toBe("avanzado");
    expect(knowledgePillarForPath("/knowledge-hub")).toBe("avanzado");
  });

  it("usa headings de página únicos y estables", () => {
    const titles = Object.values(KNOWLEDGE_HEADINGS);
    expect(new Set(titles).size).toBe(titles.length);
    expect(KNOWLEDGE_HEADINGS.overview).toBe("Resumen");
    expect(KNOWLEDGE_HEADINGS.sources).toBe("Fuentes");
    expect(KNOWLEDGE_HEADINGS.glossary).toBe("Glosario de negocio");
    expect(KNOWLEDGE_HEADINGS.review).toBe("Cola de revisión");
    expect(KNOWLEDGE_HEADINGS.learning).toBe("Aprendizaje");
    expect(KNOWLEDGE_HEADINGS.map).toBe("Mapa");
    expect(KNOWLEDGE_HEADINGS.understanding).toBe("Entendimiento");
    expect(KNOWLEDGE_ROUTE_TITLES["/knowledge"]).toBe(KNOWLEDGE_HEADINGS.overview);
    expect(KNOWLEDGE_ROUTE_TITLES["/knowledge/sources"]).toBe(KNOWLEDGE_HEADINGS.sources);
  });
});
