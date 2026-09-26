import { describe, expect, it } from "vitest";
import {
  KNOWLEDGE_ADVANCED_TABS,
  KNOWLEDGE_HEADINGS,
  KNOWLEDGE_PILLARS,
  KNOWLEDGE_ROUTE_TITLES,
  knowledgePillarForPath,
} from "./knowledgeNav";

describe("knowledge IA", () => {
  it("expone 5 pilares + Avanzado y no más de 6 pestañas primarias", () => {
    expect(KNOWLEDGE_PILLARS.map((tab) => tab.label)).toEqual([
      "Resumen",
      "Fuentes",
      "Modelo",
      "Calidad",
      "Evaluación",
    ]);
    expect(KNOWLEDGE_PILLARS.length + 1).toBeLessThanOrEqual(6);
  });

  it("no deja Aprendizaje ni Mapa como pilares", () => {
    const labels = KNOWLEDGE_PILLARS.map((tab) => tab.label);
    expect(labels).not.toContain("Aprendizaje");
    expect(labels).not.toContain("Mapa");
    expect(labels).not.toContain("Semántica");
    expect(labels).not.toContain("Términos");
  });

  it("mantiene herramientas avanzadas fuera del rail visible", () => {
    const advanced = KNOWLEDGE_ADVANCED_TABS.map((tab) => tab.to);
    expect(advanced).toContain("/knowledge/understanding");
    expect(advanced).toContain("/knowledge/jobs");
    expect(advanced).toContain("/knowledge/glossary");
    expect(advanced).toContain("/connectors");
  });

  it("resuelve el pilar activo por ruta (incluidas rutas legadas)", () => {
    expect(knowledgePillarForPath("/knowledge")).toBe("resumen");
    expect(knowledgePillarForPath("/knowledge/")).toBe("resumen");
    expect(knowledgePillarForPath("/knowledge/sources")).toBe("fuentes");
    expect(knowledgePillarForPath("/knowledge/sources/abc")).toBe("fuentes");
    expect(knowledgePillarForPath("/knowledge/add")).toBe("fuentes");
    expect(knowledgePillarForPath("/knowledge/model")).toBe("modelo");
    expect(knowledgePillarForPath("/knowledge/map")).toBe("modelo");
    expect(knowledgePillarForPath("/knowledge/quality")).toBe("calidad");
    expect(knowledgePillarForPath("/knowledge/review")).toBe("calidad");
    expect(knowledgePillarForPath("/knowledge/improvements")).toBe("calidad");
    expect(knowledgePillarForPath("/knowledge/evaluation")).toBe("evaluacion");
    expect(knowledgePillarForPath("/knowledge/activity")).toBe("avanzado");
    expect(knowledgePillarForPath("/knowledge/learning")).toBe("avanzado");
    expect(knowledgePillarForPath("/knowledge/glossary")).toBe("avanzado");
    expect(knowledgePillarForPath("/knowledge/jobs")).toBe("avanzado");
    expect(knowledgePillarForPath("/connectors")).toBe("avanzado");
  });

  it("usa headings de página únicos y estables", () => {
    const titles = Object.values(KNOWLEDGE_HEADINGS);
    expect(new Set(titles).size).toBe(titles.length);
    expect(KNOWLEDGE_HEADINGS.overview).toBe("Resumen");
    expect(KNOWLEDGE_HEADINGS.model).toBe("Modelo del negocio");
    expect(KNOWLEDGE_HEADINGS.quality).toBe("Calidad");
    expect(KNOWLEDGE_HEADINGS.evaluation).toBe("Evaluación");
    expect(KNOWLEDGE_ROUTE_TITLES["/knowledge"]).toBe(KNOWLEDGE_HEADINGS.overview);
    expect(KNOWLEDGE_ROUTE_TITLES["/knowledge/model"]).toBe(KNOWLEDGE_HEADINGS.model);
    expect(KNOWLEDGE_ROUTE_TITLES["/knowledge/learning"]).toBe(
      KNOWLEDGE_HEADINGS.activity
    );
  });
});
