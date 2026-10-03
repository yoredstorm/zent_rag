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
      "Inicio",
      "Explorador",
      "Salud",
      "Fuentes",
      "Actividad",
    ]);
    expect(KNOWLEDGE_PILLARS.length + 1).toBeLessThanOrEqual(6);
  });

  it("habla de conocimiento, no de pipeline", () => {
    const labels = KNOWLEDGE_PILLARS.map((tab) => tab.label);
    expect(labels).not.toContain("Aprendizaje");
    expect(labels).not.toContain("Mapa");
    expect(labels).not.toContain("Modelo");
    expect(labels).not.toContain("Calidad");
  });

  it("mantiene herramientas avanzadas fuera del rail visible", () => {
    const advanced = KNOWLEDGE_ADVANCED_TABS.map((tab) => tab.to);
    expect(advanced).toContain("/knowledge/evaluation");
    expect(advanced).toContain("/knowledge/understanding");
    expect(advanced).toContain("/knowledge/jobs");
    expect(advanced).toContain("/knowledge/glossary");
    expect(advanced).toContain("/connectors");
  });

  it("resuelve el pilar activo por ruta (incluidas rutas legadas)", () => {
    expect(knowledgePillarForPath("/knowledge")).toBe("inicio");
    expect(knowledgePillarForPath("/knowledge/")).toBe("inicio");
    expect(knowledgePillarForPath("/knowledge/search")).toBe("inicio");
    expect(knowledgePillarForPath("/knowledge/explorer")).toBe("explorador");
    expect(knowledgePillarForPath("/knowledge/objects/abc")).toBe("explorador");
    expect(knowledgePillarForPath("/knowledge/model")).toBe("explorador");
    expect(knowledgePillarForPath("/knowledge/map")).toBe("explorador");
    expect(knowledgePillarForPath("/knowledge/health")).toBe("salud");
    expect(knowledgePillarForPath("/knowledge/quality")).toBe("salud");
    expect(knowledgePillarForPath("/knowledge/review")).toBe("salud");
    expect(knowledgePillarForPath("/knowledge/improvements")).toBe("salud");
    expect(knowledgePillarForPath("/knowledge/sources")).toBe("fuentes");
    expect(knowledgePillarForPath("/knowledge/sources/abc")).toBe("fuentes");
    expect(knowledgePillarForPath("/knowledge/add")).toBe("fuentes");
    expect(knowledgePillarForPath("/knowledge/activity")).toBe("actividad");
    expect(knowledgePillarForPath("/knowledge/learning")).toBe("actividad");
    expect(knowledgePillarForPath("/knowledge/evaluation")).toBe("avanzado");
    expect(knowledgePillarForPath("/knowledge/glossary")).toBe("avanzado");
    expect(knowledgePillarForPath("/knowledge/jobs")).toBe("avanzado");
    expect(knowledgePillarForPath("/connectors")).toBe("avanzado");
  });

  it("usa headings de página únicos y estables", () => {
    const primary = [
      KNOWLEDGE_HEADINGS.home,
      KNOWLEDGE_HEADINGS.explorer,
      KNOWLEDGE_HEADINGS.health,
      KNOWLEDGE_HEADINGS.sources,
      KNOWLEDGE_HEADINGS.activity,
      KNOWLEDGE_HEADINGS.evaluation,
      KNOWLEDGE_HEADINGS.search,
      KNOWLEDGE_HEADINGS.object,
    ];
    expect(new Set(primary).size).toBe(primary.length);
    expect(KNOWLEDGE_HEADINGS.home).toBe("Conocimiento");
    expect(KNOWLEDGE_HEADINGS.explorer).toBe("Explorador");
    expect(KNOWLEDGE_HEADINGS.health).toBe("Salud");
    expect(KNOWLEDGE_HEADINGS.evaluation).toBe("Evaluación");
    expect(KNOWLEDGE_ROUTE_TITLES["/knowledge"]).toBe(KNOWLEDGE_HEADINGS.home);
    expect(KNOWLEDGE_ROUTE_TITLES["/knowledge/explorer"]).toBe(
      KNOWLEDGE_HEADINGS.explorer
    );
    expect(KNOWLEDGE_ROUTE_TITLES["/knowledge/health"]).toBe(KNOWLEDGE_HEADINGS.health);
    expect(KNOWLEDGE_ROUTE_TITLES["/knowledge/learning"]).toBe(
      KNOWLEDGE_HEADINGS.activity
    );
  });
});
