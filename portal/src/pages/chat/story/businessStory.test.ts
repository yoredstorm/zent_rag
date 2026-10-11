import { describe, expect, it } from "vitest";
import {
  executionStoryPath,
  translateBusinessSteps,
  translateReasonCode,
  type BusinessStep,
} from "./businessStory";

describe("businessStory (P7)", () => {
  it("construye el path del endpoint unificado", () => {
    expect(executionStoryPath({ kind: "agent", id: "r-1" })).toBe(
      "/api/v1/executions/agent/r-1/story?view=business",
    );
    expect(executionStoryPath({ kind: "agent", id: "r-1" }, "technical")).toBe(
      "/api/v1/executions/agent/r-1/story?view=technical",
    );
  });

  it("traduce los reason codes de evidencia y respuesta", () => {
    expect(translateReasonCode("EVIDENCE_COMPLETE").title).toBe(
      "Evidencia suficiente",
    );
    expect(translateReasonCode("EVIDENCE_COMPLETE").tone).toBe("ok");
    expect(translateReasonCode("ANSWER_LIMITED").title).toBe(
      "Respuesta con límites",
    );
    expect(translateReasonCode("TOOL_FAILED").tone).toBe("error");
    expect(translateReasonCode("RETRIEVAL_UNAVAILABLE").caption).toContain(
      "fallo operativo",
    );
  });

  it("AUTHORITY_* usa el tono del step y no inventa códigos", () => {
    const copy = translateReasonCode("AUTHORITY_UNDETERMINED", "warn");
    expect(copy.title).toBe("Resolución de autoridad");
    expect(copy.tone).toBe("warn");
  });

  it("código desconocido cae al texto del código sin romper", () => {
    const copy = translateReasonCode("SOMETHING_NEW");
    expect(copy.title).toBe("SOMETHING_NEW");
    expect(copy.tone).toBe("neutral");
  });

  it("traduce una lista de steps con tono por status", () => {
    const steps: BusinessStep[] = [
      { type: "evidence_evaluation", status: "ok", reason_code: "EVIDENCE_COMPLETE" },
      {
        type: "answer_decision",
        status: "warn",
        reason_code: "ANSWER_LIMITED",
      },
      { type: "consistency_check", status: "error", reason_code: "CONSISTENCY_VIOLATIONS" },
    ];
    const translated = translateBusinessSteps(steps);
    expect(translated.map((step) => step.tone)).toEqual(["ok", "warn", "error"]);
    expect(translated[1].title).toBe("Respuesta con límites");
  });
});
