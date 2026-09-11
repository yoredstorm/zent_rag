import { describe, expect, it } from "vitest";
import { WIZARD_STEP_HEADINGS, WIZARD_STEPS, canContinueAnalyze } from "./types";

describe("wizard steps 3–6 — headings and Continuar", () => {
  it("expone headings exactos y estables para Analizar–Listo", () => {
    expect(WIZARD_STEP_HEADINGS.analyze).toBe("Analizar");
    expect(WIZARD_STEP_HEADINGS.review).toBe("Revisar");
    expect(WIZARD_STEP_HEADINGS.test).toBe("Probar");
    expect(WIZARD_STEP_HEADINGS.ready).toBe("Listo");
    expect(WIZARD_STEPS.filter((s) => s.id in WIZARD_STEP_HEADINGS).map((s) => s.label)).toEqual([
      "Analizar",
      "Revisar",
      "Probar",
      "Listo",
    ]);
    const titles = Object.values(WIZARD_STEP_HEADINGS);
    expect(new Set(titles).size).toBe(titles.length);
  });

  it("Continuar es no-op hasta que el análisis termina", () => {
    expect(canContinueAnalyze("ANALYZING")).toBe(false);
    expect(canContinueAnalyze("DISCOVERING")).toBe(false);
    expect(canContinueAnalyze("CONNECTED")).toBe(false);
    expect(canContinueAnalyze("FAILED")).toBe(false);
    expect(canContinueAnalyze(null)).toBe(false);
    expect(canContinueAnalyze(undefined)).toBe(false);
    expect(canContinueAnalyze("REVIEW_REQUIRED")).toBe(true);
    expect(canContinueAnalyze("TESTING")).toBe(true);
    expect(canContinueAnalyze("READY")).toBe(true);
    expect(canContinueAnalyze("NEEDS_ATTENTION")).toBe(true);
  });
});
