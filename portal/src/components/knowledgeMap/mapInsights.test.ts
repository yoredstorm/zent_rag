// =============================================================================
// mapInsights — LOD, strength, evidence path y timeline del Knowledge Map
// =============================================================================
import { describe, expect, it } from "vitest";

import type {
  KnowledgeDomain,
  KnowledgeObjectDetail,
} from "../../lib/knowledgeModel";
import {
  buildEvidencePath,
  buildTimeline,
  deriveKnowledgeStrength,
  domainCoverage,
  layoutDomains,
  layoutGraph,
  layoutTopics,
} from "./mapInsights";

function domain(patch: Partial<KnowledgeDomain> = {}): KnowledgeDomain {
  return {
    name: "ATPCO",
    objects: 12431,
    verified: 9000,
    measured: true,
    avg_confidence: 0.9,
    sources: 7,
    edges: 2400,
    conflicts: 0,
    last_updated: new Date().toISOString(),
    by_type: [
      { type: "entity", total: 800, verified: 400 },
      { type: "business_rule", total: 120, verified: 40 },
    ],
    ...patch,
  };
}

function detail(patch: Partial<KnowledgeObjectDetail> = {}): KnowledgeObjectDetail {
  const now = new Date().toISOString();
  return {
    object: {
      id: "obj-1",
      type: "concept",
      name: "Record 4",
      display_name: "Record 4",
      description: "Registro de control de renumbering.",
      domain: "ATPCO",
      status: "inferred",
      provenance: "INFERRED",
      confidence: 0.82,
      confidence_label: "alta",
      source_of_truth: null,
      source_id: "src-1",
      authority_level: null,
      evidence_count: 26,
      assertion_count: 3,
      verified_at: null,
      freshness_at: null,
      last_seen_at: null,
      metadata: {},
      created_at: now,
      updated_at: now,
    },
    edges: [
      {
        id: "edge-1",
        subject_id: "obj-1",
        subject_name: "Record 4",
        predicate: "modifies",
        object_id: "obj-2",
        object_name: "Record 2",
        direction: "out",
        relationship_type: "business",
        confidence: 0.8,
        status: "inferred",
        provenance: "INFERRED",
        evidence: [],
        metadata: {},
      },
    ],
    assertions: [
      {
        id: "assert-1",
        subject_id: "obj-1",
        subject_label: "Record 4",
        predicate: "has_field",
        object_id: null,
        object_value: "Sequence Number",
        assertion_type: "structural",
        confidence: 0.8,
        confidence_detail: {
          components: {
            evidence_strength: 0.9,
            source_reliability: 0.8,
            corroboration: 0.7,
            semantic_certainty: 0.6,
            freshness: 1,
          },
          formula: "product(component^weight)",
        },
        status: "candidate",
        provenance: "INFERRED",
        method: "compiler",
        source_id: "src-1",
        evidence_count: 2,
        version: 1,
        verified_at: null,
        stale_at: null,
        valid_from: "2025-01-01T00:00:00+00:00",
        valid_to: null,
        created_at: now,
        updated_at: now,
      },
    ],
    evidence: [
      {
        id: "ev-1",
        source_id: "src-1",
        document_id: "doc-1",
        page: 7,
        section_path: ["Record 4"],
        locator: "p7",
        table_reference: null,
        database_reference: null,
        excerpt: "Record 4 controla el renumbering.",
        evidence_type: "document",
        strength: 0.9,
        authority: "primary",
        retrieval_score: null,
        content_hash: "hash",
        created_at: now,
      },
    ],
    versions: [
      {
        version: 2,
        change_kind: "updated",
        snapshot: {},
        changed_by: null,
        reason: "Nueva versión 2026",
        created_at: now,
      },
      {
        version: 1,
        change_kind: "created",
        snapshot: {},
        changed_by: null,
        reason: null,
        created_at: "2024-05-01T00:00:00+00:00",
      },
    ],
    lineage: { physical_refs: [], lineage: [], count: 0 },
    impact: { object: "Record 4", dependents: [], count: 0 },
    questions: [],
    ...patch,
  };
}

describe("layoutDomains", () => {
  it("crea un cluster por dominio con tamaño proporcional y tono por conflicto", () => {
    const layout = layoutDomains([
      domain(),
      domain({ name: "Sabre", objects: 100, conflicts: 2, verified: 10 }),
      domain({ name: "Vacío", objects: 0 }),
    ]);
    expect(layout.nodes).toHaveLength(2);
    const atpco = layout.nodes.find((node) => node.label === "ATPCO")!;
    const sabre = layout.nodes.find((node) => node.label === "Sabre")!;
    expect(atpco.size).toBeGreaterThan(sabre.size);
    expect(sabre.tone).toBe("warn");
  });
});

describe("layoutTopics", () => {
  it("conecta el dominio con sus temas reales", () => {
    const layout = layoutTopics(domain());
    expect(layout.nodes[0].label).toBe("ATPCO");
    expect(layout.nodes.map((node) => node.label)).toContain("Entidades");
    expect(layout.edges).toHaveLength(2);
    expect(layout.edges[0].label).toBe("contiene");
  });

  it("sin temas devuelve un layout vacío", () => {
    expect(layoutTopics(domain({ by_type: [] })).nodes).toHaveLength(0);
    expect(layoutTopics(null).nodes).toHaveLength(0);
  });
});

describe("layoutGraph", () => {
  it("limita nodos, respeta el foco y filtra aristas huérfanas", () => {
    const layout = layoutGraph(
      {
        nodes: [
          { id: "n1", type: "entity", name: "Record 4", status: "inferred", confidence: 0.8, evidence_count: 3, degree: 5 },
          { id: "n2", type: "entity", name: "Record 2", status: "verified", confidence: 0.9, evidence_count: 4, degree: 2 },
          { id: "n3", type: "entity", name: "Fuera", status: "inferred", confidence: 0.5, evidence_count: 1, degree: 0 },
        ],
        edges: [
          { id: "e1", source: "n1", target: "n2", predicate: "modifies", confidence: 0.8 },
          { id: "e2", source: "n1", target: "n9", predicate: "x", confidence: 0.5 },
        ],
        focus_id: "n1",
      },
      2
    );
    expect(layout.nodes).toHaveLength(2);
    expect(layout.nodes[0].x).toBe(50);
    expect(layout.edges).toHaveLength(1);
    expect(layout.nodes.find((node) => node.id === "n2")!.tone).toBe("ok");
  });
});

describe("deriveKnowledgeStrength", () => {
  it("agrega componentes reales y explica la fórmula", () => {
    const strength = deriveKnowledgeStrength(detail(), { conflicts: 0 });
    expect(strength.score).toBe(0.82);
    const evidence = strength.components.find((c) => c.key === "evidence_strength")!;
    expect(evidence.display).toBe("90%");
    const sources = strength.components.find(
      (c) => c.key === "independent_sources"
    )!;
    expect(sources.display).toBe("1");
    const consistency = strength.components.find((c) => c.key === "consistency")!;
    expect(consistency.display).toBe("Sin conflictos");
    expect(strength.explanation).toMatch(/techo 0.6/);
  });

  it("sin detalle no inventa score", () => {
    const strength = deriveKnowledgeStrength(null);
    expect(strength.score).toBeNull();
    expect(strength.components).toHaveLength(0);
  });
});

describe("buildEvidencePath", () => {
  it("construye objeto, hecho, evidencia, fuente y página", () => {
    const path = buildEvidencePath(detail(), { "src-1": "Rec4_dapp_C.pdf" });
    expect(path.map((step) => step.kind)).toEqual([
      "object",
      "assertion",
      "evidence",
      "source",
      "page",
    ]);
    expect(path[3].label).toBe("Rec4_dapp_C.pdf");
    expect(path[4].label).toBe("Página 7");
  });
});

describe("buildTimeline", () => {
  it("mezcla versiones y vigencia temporal ordenado por fecha", () => {
    const timeline = buildTimeline(detail());
    expect(timeline.some((entry) => entry.kind === "version")).toBe(true);
    expect(timeline.some((entry) => entry.kind === "temporal")).toBe(true);
    const dates = timeline.map((entry) => (entry.at ? Date.parse(entry.at) : 0));
    expect([...dates].sort((a, b) => b - a)).toEqual(dates);
  });
});

describe("domainCoverage", () => {
  it("usa verificados sobre objetos de negocio", () => {
    const coverage = domainCoverage(domain({ objects: 100, verified: 82 }));
    expect(coverage.pct).toBe(82);
    expect(coverage.formula).toMatch(/verificados/);
  });
});
