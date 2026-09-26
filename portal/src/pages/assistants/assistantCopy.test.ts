import { describe, expect, it } from "vitest";
import {
  ASSISTANT_TAB_LABEL,
  ASSISTANT_TABS,
  humanizeActivityTitle,
  modelHumanLabel,
  parseAssistantTab,
  toolHumanLabel,
  workflowStatusLabel,
} from "./assistantCopy";

describe("parseAssistantTab", () => {
  it("acepta las 3 pestañas canónicas y alias viejos a Qué hace", () => {
    expect(ASSISTANT_TABS).toEqual(["resumen", "automatizaciones", "actividad"]);
    expect(ASSISTANT_TAB_LABEL.resumen).toBe("Qué hace");
    expect(parseAssistantTab(null)).toBe("resumen");
    expect(parseAssistantTab("actividad")).toBe("actividad");
    expect(parseAssistantTab("conocimiento")).toBe("resumen");
    expect(parseAssistantTab("permisos")).toBe("resumen");
    expect(parseAssistantTab("ajustes")).toBe("resumen");
    expect(parseAssistantTab("no-existe")).toBe("resumen");
  });
});

describe("labels humanas", () => {
  it("traduce modelo, tools y status de workflow", () => {
    expect(modelHumanLabel("zent-default")).toBe("Automático · zent-default");
    expect(modelHumanLabel("zent-cheap")).toBe("Priorizar economía · zent-cheap");
    expect(toolHumanLabel("search_knowledge")).toBe("Consultar conocimiento");
    expect(toolHumanLabel("desconocida")).toBe("desconocida");
    expect(workflowStatusLabel("active")).toBe("Activo");
  });

  it("cambia el prefijo El agente por El asistente", () => {
    expect(humanizeActivityTitle("El agente analizó la información")).toBe(
      "El asistente analizó la información",
    );
    expect(humanizeActivityTitle("Stock bajo detectado")).toBe("Stock bajo detectado");
  });
});
