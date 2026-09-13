import { describe, expect, it } from "vitest";
import {
  analyzePercent,
  buildAnalyzeGlimpses,
  formatAskEvidence,
  selectDigestHighlights,
} from "./wizardUx";
import {
  WIZARD_STEP_HEADINGS,
  WIZARD_STEPS,
  canContinueAnalyze,
  type Suggestion,
} from "./types";

function fact(
  id: string,
  factType: string,
  title: string,
  value = title,
  extra: Partial<Suggestion> = {}
): Suggestion {
  return {
    id,
    type: "document_fact",
    title,
    description: value,
    confidence: "high",
    evidence: [],
    payload: { fact_type: factType, key: title, value },
    ...extra,
  };
}

function mapping(
  id: string,
  title: string,
  confidence: string,
  extra: Partial<Suggestion> = {}
): Suggestion {
  return {
    id,
    type: "field_mapping",
    title,
    description: title,
    confidence,
    evidence: [],
    payload: { business_name: title },
    ...extra,
  };
}

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

describe("selectDigestHighlights", () => {
  it("cap 6: party e identifier primero, luego amount y date, máx 2 cláusulas", () => {
    const items = [
      fact("c1", "clause", "Jurisdicción"),
      fact("c2", "clause", "Responsabilidad"),
      fact("d1", "date", "Vigencia", "10 años"),
      fact("c3", "clause", "Excepciones"),
      fact("c4", "clause", "Obligaciones"),
      fact("c5", "clause", "Propiedad intelectual"),
      fact("id1", "identifier", "DNI Empleado", "45272666"),
      fact("p1", "party", "Empleado", "Juan Pérez"),
      fact("id2", "identifier", "RUC Empresa", "2053592914"),
      fact("p2", "party", "Empresa", "AIR FRANCE"),
      fact("c6", "clause", "Objeto"),
      fact("a1", "amount", "Monto", "29733"),
      fact("c7", "clause", "Definición"),
    ];
    const { highlights, rest } = selectDigestHighlights(items, { flow: "documents" });
    expect(highlights.map((h) => h.id)).toEqual(["p1", "p2", "id1", "id2", "a1", "d1"]);
    expect(rest.map((h) => h.id)).toEqual(["c1", "c2", "c3", "c4", "c5", "c6", "c7"]);
  });

  it("trata DNI/RUC por título cuando fact_type no es identifier", () => {
    const items = [
      fact("c1", "clause", "Objeto"),
      fact("x1", "fact", "DNI Empleado", "1"),
      fact("x2", "fact", "RUC Empresa", "2"),
      fact("p1", "party", "Empresa", "Acme"),
    ];
    const { highlights } = selectDigestHighlights(items, { kind: "document" });
    expect(highlights.map((h) => h.id)).toEqual(["p1", "x1", "x2", "c1"]);
  });

  it("llena con 1–2 cláusulas si queda cupo", () => {
    const items = [
      fact("p1", "party", "Parte A"),
      fact("c1", "clause", "Renovación"),
      fact("c2", "clause", "Confidencialidad"),
      fact("c3", "clause", "Pago"),
    ];
    const { highlights, rest } = selectDigestHighlights(items, { flow: "documents" });
    expect(highlights.map((h) => h.id)).toEqual(["p1", "c1", "c2"]);
    expect(rest.map((h) => h.id)).toEqual(["c3"]);
  });

  it("tabular: mappings inciertos primero, cap 6", () => {
    const items = [
      mapping("h1", "sku", "high"),
      mapping("l1", "col_x", "low"),
      mapping("m1", "precio", "medium", { evidence: ["a", "b"] }),
      mapping("h2", "stock", "high"),
      mapping("l2", "misc", "low"),
      mapping("h3", "nombre", "high"),
      mapping("h4", "fecha", "high"),
      mapping("h5", "extra", "high"),
    ];
    const { highlights, rest } = selectDigestHighlights(items, { flow: "spreadsheets" });
    expect(highlights.map((h) => h.id)).toEqual(["l1", "m1", "l2", "h1", "h2", "h3"]);
    expect(rest.map((h) => h.id)).toEqual(["h4", "h5"]);
  });

  it("lista corta: todo highlight, rest vacío", () => {
    const items = [fact("p1", "party", "Acme")];
    const { highlights, rest } = selectDigestHighlights(items, { flow: "documents" });
    expect(highlights).toEqual(items);
    expect(rest).toEqual([]);
  });
});

describe("analyzePercent", () => {
  const phases = [
    { id: "a", state: "done" },
    { id: "b", state: "done" },
    { id: "c", state: "active" },
    { id: "d", state: "pending" },
  ];

  it("es fases done / total * 100", () => {
    expect(analyzePercent({ phases, status: "ANALYZING" })).toBe(50);
  });

  it("promedia con job_progress cuando existe", () => {
    expect(analyzePercent({ phases, status: "ANALYZING", jobProgress: 80 })).toBe(65);
  });

  it("ANALYZING sin job no pasa de 90", () => {
    const allDone = [
      { id: "a", state: "done" },
      { id: "b", state: "done" },
    ];
    expect(analyzePercent({ phases: allDone, status: "ANALYZING" })).toBe(90);
  });

  it("status terminal es 100", () => {
    expect(analyzePercent({ phases, status: "REVIEW_REQUIRED" })).toBe(100);
    expect(analyzePercent({ phases: [], status: "READY" })).toBe(100);
  });
});

describe("buildAnalyzeGlimpses", () => {
  it("arma frases de facts de documento, máx 12", () => {
    const glimpses = buildAnalyzeGlimpses({
      facts: [
        { fact_type: "party", key: "Empresa", value: "AIR FRANCE" },
        { fact_type: "identifier", key: "DNI", value: "45272666" },
        { fact_type: "amount", key: "Monto", value: "29733" },
        { fact_type: "date", key: "Vigencia", value: "10 años" },
        { fact_type: "clause", key: "Objeto", value: "NDA laboral" },
      ],
    });
    expect(glimpses.map((g) => g.text)).toEqual([
      "Ah, Empresa es AIR FRANCE",
      "Ah, DNI es 45272666",
      "Vi un monto: 29733",
      "Fecha: 10 años",
      "NDA laboral",
    ]);
    expect(glimpses[0].id).toBeTruthy();
  });

  it("tabular usa entidad y columnas", () => {
    const glimpses = buildAnalyzeGlimpses({
      likely_entity: "Producto",
      columns: [
        { physical_name: "precio" },
        { physical_name: "sku" },
      ],
    });
    expect(glimpses.map((g) => g.text)).toEqual([
      "Esto parece Producto",
      "Columna precio…",
      "Columna sku…",
    ]);
  });

  it("sin facts ni columnas: lista vacía", () => {
    expect(buildAnalyzeGlimpses({})).toEqual([]);
  });
});

describe("formatAskEvidence", () => {
  it("no convierte objetos en [object Object]", () => {
    const labels = formatAskEvidence([
      {
        evidence_id: "ev-1",
        type: "document_chunk",
        source_name: "NDA AIR FRANCE.pdf",
        snippet: "LA EMPRESA: AIR FRANCE PROCESSING CENTER S.A.C.",
      },
      {
        type: "document_chunk",
        source_name: "NDA AIR FRANCE.pdf",
        snippet: "EL EMPLEADO: PIMENTEL ARENAS PABLO JESUS",
      },
    ]);
    expect(labels.join(" ")).not.toContain("[object Object]");
    expect(labels[0]).toContain("NDA AIR FRANCE.pdf");
    expect(labels[0]).toContain("AIR FRANCE PROCESSING CENTER");
    expect(labels[1]).toContain("PIMENTEL");
  });

  it("deja strings intactos y descarta vacíos", () => {
    expect(formatAskEvidence(["página 1", "  ", { source_name: "" }])).toEqual(["página 1"]);
  });
});
