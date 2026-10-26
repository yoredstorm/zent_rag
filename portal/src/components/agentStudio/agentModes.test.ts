import { describe, expect, it } from "vitest";
import {
  CUSTOM_PROFILE,
  DEFAULT_MODEL_ROUTE,
  MODEL_PRIORITIES,
  capabilityLabels,
  capabilityStates,
  flagsFromTools,
  intelligenceMode,
  intelligenceSummary,
  limitsMode,
  limitsSummary,
  applyPresetToProfile,
  matchResponsePreset,
  modelMode,
  modelSummary,
  recommendAgentConfiguration,
  responseProfileSummary,
  retrievalMode,
  retrievalSummary,
} from "./agentModes";
import {
  DEFAULT_RESPONSE_PROFILE,
  type ResponseProfilePreset,
} from "./types";

// Fixture de test: el catálogo real viene del backend.
const RESPONSE_PROFILE_PRESETS: ResponseProfilePreset[] = [
  {
    id: "balanced",
    label: "Equilibrado",
    hint: "",
    profile: { ...DEFAULT_RESPONSE_PROFILE, profile_id: "balanced" },
  },
  {
    id: "analytical",
    label: "Analítico",
    hint: "",
    profile: {
      ...DEFAULT_RESPONSE_PROFILE,
      profile_id: "analytical",
      default_detail: "deep",
      use_examples: true,
      show_uncertainty: true,
      analysis_depth: "hypothesis_and_tradeoffs",
    },
  },
  {
    id: "concise",
    label: "Conciso",
    hint: "",
    profile: {
      ...DEFAULT_RESPONSE_PROFILE,
      profile_id: "concise",
      default_detail: "brief",
      use_examples: false,
      use_tables: false,
      use_headings: false,
      show_practical_implications: false,
      communication_strategy: "answer_only",
      detail_budget: "minimal",
      structure_policy: "answer_only",
      example_policy: "never",
      analysis_depth: "answer_only",
      terminology_policy: "plain",
      source_presentation_policy: "only_when_required",
    },
  },
];

describe("Auto vs Personalizado", () => {
  it("el modelo es Automático sólo con la ruta recomendada", () => {
    expect(modelMode("")).toBe("auto");
    expect(modelMode(DEFAULT_MODEL_ROUTE)).toBe("auto");
    expect(modelMode("zent-quality")).toBe("custom");
    expect(modelMode("openai/gpt-4o-mini")).toBe("custom");
  });

  it("la búsqueda es Automática con los valores recomendados", () => {
    expect(retrievalMode({ strategy: "hybrid", top_k: 10, score_threshold: 0 })).toBe("auto");
    expect(retrievalMode({ strategy: "vector", top_k: 8, score_threshold: 0.1 })).toBe("custom");
    expect(retrievalMode({ strategy: "hybrid", top_k: 8, score_threshold: 0 })).toBe("custom");
  });

  it("los límites son Protección recomendada sólo con los tres topes por defecto", () => {
    expect(limitsMode(null)).toBe("auto");
    expect(limitsMode({ max_steps: 8, max_tokens: 4000, max_cost_usd: 0.5 })).toBe("auto");
    expect(limitsMode({ max_steps: 12, max_tokens: 4000, max_cost_usd: 0.5 })).toBe("custom");
    expect(limitsMode({ max_steps: null, max_tokens: null, max_cost_usd: null })).toBe("auto");
  });

  it("la inteligencia hereda si no hay ningún override definido", () => {
    expect(intelligenceMode(null)).toBe("auto");
    expect(intelligenceMode(undefined)).toBe("auto");
    expect(intelligenceMode({ tool_routing: null, answer_gate: null })).toBe("auto");
    expect(intelligenceMode({ answer_gate: false })).toBe("custom");
    expect(intelligenceMode({ tool_routing: true })).toBe("custom");
    // `jev_loop` no se edita en el Studio, pero un agente legacy puede tenerlo.
    expect(intelligenceMode({ jev_loop: "off" })).toBe("custom");
  });
});

describe("resúmenes de estado", () => {
  it("nunca muestra un valor técnico suelto", () => {
    expect(modelSummary(DEFAULT_MODEL_ROUTE)).toBe("Automático · Zent elige el motor");
    expect(modelSummary("zent-quality")).toBe("Priorizar calidad · zent-quality");
    expect(retrievalSummary({ strategy: "hybrid", top_k: 10, score_threshold: 0 })).toBe(
      "Automática · búsqueda híbrida · 10 fragmentos",
    );
    expect(retrievalSummary({ strategy: "lexical", top_k: 4, score_threshold: 0 })).toBe(
      "Personalizada · por palabras exactas · 4 fragmentos",
    );
    expect(limitsSummary(null)).toContain("Protección automática");
    expect(limitsSummary({ max_steps: 12, max_tokens: 4000, max_cost_usd: 0.5 })).toBe(
      "Personalizado · 12 pasos · 4000 tokens · USD 0.50",
    );
  });

  it("explica cada override de JEV con una palabra, no con un booleano", () => {
    expect(intelligenceSummary(null)).toBe(
      "Ruteo de herramientas: heredado · Corte por evidencia: heredado · Verificación: heredado",
    );
    expect(intelligenceSummary({ tool_routing: false, answer_gate: true })).toContain(
      "Ruteo de herramientas: apagado",
    );
  });

  it("todas las prioridades de modelo exponen su alias técnico", () => {
    for (const priority of MODEL_PRIORITIES) {
      expect(priority.tech).toBe(priority.value);
      expect(priority.hint.length).toBeGreaterThan(0);
    }
  });
});

describe("presets de comportamiento", () => {
  it("un perfil ausente equivale al preset recomendado, no a Personalizado", () => {
    expect(matchResponsePreset(null, RESPONSE_PROFILE_PRESETS)).toBe("balanced");
    expect(matchResponsePreset(undefined, RESPONSE_PROFILE_PRESETS)).toBe("balanced");
  });

  it("reconoce cada preset resuelto", () => {
    for (const preset of RESPONSE_PROFILE_PRESETS) {
      const resolved = { ...DEFAULT_RESPONSE_PROFILE, ...preset.profile, preset: preset.id };
      expect(matchResponsePreset(resolved, RESPONSE_PROFILE_PRESETS)).toBe(preset.id);
    }
  });

  it("un perfil con valores propios es Personalizado y no se confunde con un preset", () => {
    expect(
      matchResponsePreset(
        { ...DEFAULT_RESPONSE_PROFILE, tone: "executive" },
        RESPONSE_PROFILE_PRESETS,
      ),
    ).toBe(CUSTOM_PROFILE);
    expect(
      matchResponsePreset(
        { ...DEFAULT_RESPONSE_PROFILE, custom_instructions: "Sé breve" },
        RESPONSE_PROFILE_PRESETS,
      ),
    ).toBe(CUSTOM_PROFILE);
    expect(
      matchResponsePreset(
        { ...DEFAULT_RESPONSE_PROFILE, preferred_blueprints: ["comparison"] },
        RESPONSE_PROFILE_PRESETS,
      ),
    ).toBe(CUSTOM_PROFILE);
  });

  it("el resumen del perfil personalizado describe el estilo, no el preset", () => {
    const resumen = responseProfileSummary(
      {
        ...DEFAULT_RESPONSE_PROFILE,
        tone: "didactic",
        default_detail: "deep",
        cite_sources: false,
      },
      RESPONSE_PROFILE_PRESETS,
    );
    expect(resumen).toBe("Personalizado · didáctico · profundo · sin citas");
  });

  it("cambiar de Analítico a Conciso elimina los campos exclusivos del anterior", () => {
    const analytical = RESPONSE_PROFILE_PRESETS[1];
    const concise = RESPONSE_PROFILE_PRESETS[2];
    const before = applyPresetToProfile(analytical);
    expect(before.use_examples).toBe(true);
    expect(before.analysis_depth).toBe("hypothesis_and_tradeoffs");
    const after = applyPresetToProfile(concise);
    expect(after.default_detail).toBe("brief");
    expect(after.use_examples).toBe(false);
    expect(after.use_tables).toBe(false);
    expect(after.analysis_depth).toBe("answer_only");
    expect(after.profile_id).toBe("concise");
  });
});

describe("capacidades según las fuentes", () => {
  it("Consulta datos queda indisponible sin fuentes de base de datos", () => {
    const states = capabilityStates(
      { knowledge: true, data: false, integrations: false },
      { dbAvailable: false },
    );
    const data = states.find((state) => state.id === "data");
    expect(data?.available).toBe(false);
    expect(data?.unavailableHint).toMatch(/no incluyen base de datos/);
    expect(data?.tech).toEqual(["query_database"]);
  });

  it("modela el conocimiento con sus dos tools reales", () => {
    const states = capabilityStates(
      { knowledge: true, data: true, integrations: true },
      { dbAvailable: true },
    );
    expect(states.find((state) => state.id === "knowledge")?.tech).toEqual([
      "search_knowledge",
      "query_tabular_data",
    ]);
  });

  it("deriva las capacidades de las tools persistidas", () => {
    expect(flagsFromTools(["search_knowledge", "call_api"])).toEqual({
      knowledge: true,
      data: false,
      integrations: true,
    });
    expect(flagsFromTools(["query_tabular_data"]).knowledge).toBe(true);
    expect(capabilityLabels({ knowledge: true, data: false, integrations: true })).toEqual([
      "Consultar conocimiento",
      "Usar integraciones externas",
    ]);
  });
});

describe("recomendación automática", () => {
  it("nunca enciende una capacidad que el agente no pueda usar", () => {
    const sinSql = recommendAgentConfiguration({ purpose: "", sourceTypes: ["file", "pdf"] });
    expect(sinSql.capabilities).toEqual({ knowledge: true, data: false, integrations: false });

    const conSql = recommendAgentConfiguration({ purpose: "", sourceTypes: ["sql"] });
    expect(conSql.capabilities.data).toBe(true);
  });

  it("sin fuentes no propone capacidades de conocimiento", () => {
    const recomendacion = recommendAgentConfiguration({ purpose: "Responder preguntas", sourceTypes: [] });
    expect(recomendacion.capabilities.knowledge).toBe(false);
  });

  it("elige el preset según el propósito, con su razón", () => {
    expect(
      recommendAgentConfiguration({ purpose: "Verificar normativa ATPCO", sourceTypes: ["file"] }).presetId,
    ).toBe("evidence_first");
    expect(
      recommendAgentConfiguration({ purpose: "Resumen para el directorio", sourceTypes: ["file"] }).presetId,
    ).toBe("executive");
    expect(
      recommendAgentConfiguration({ purpose: "Consultas SQL y logs", sourceTypes: ["sql"] }).presetId,
    ).toBe("technical_detailed");
    expect(
      recommendAgentConfiguration({ purpose: "Capacitar gente nueva", sourceTypes: ["file"] }).presetId,
    ).toBe("clear_didactic");
    const equilibrado = recommendAgentConfiguration({ purpose: "Atender consultas", sourceTypes: ["file"] });
    expect(equilibrado.presetId).toBe("balanced");
    expect(equilibrado.reasons.join(" ")).toMatch(/equilibrio recomendado/);
  });

  it("el modelo recomendado es Automático y JEV queda en automático", () => {
    const recomendacion = recommendAgentConfiguration({ purpose: "x", sourceTypes: ["file"] });
    expect(recomendacion.model).toBe(DEFAULT_MODEL_ROUTE);
    expect(recomendacion.decisions).toContain("JEV automático");
    expect(recomendacion.decisions).toContain("Modelo equilibrado");
  });
});
