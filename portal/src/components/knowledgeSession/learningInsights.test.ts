// =============================================================================
// learningInsights — derivaciones puras de la sesión
// =============================================================================
import { describe, expect, it } from "vitest";

import type {
  LearningSessionDetail,
  SessionEvent,
} from "../../lib/knowledgeSessions";
import {
  deriveMatches,
  deriveMilestones,
  deriveRecognizedTables,
  deriveStageInsights,
  sessionDurationMs,
  taxonomyCounts,
} from "./learningInsights";

function event(
  seq: number,
  event_type: string,
  payload: Record<string, unknown> = {},
  overrides: Partial<SessionEvent> = {}
): SessionEvent {
  return {
    seq,
    session_id: "sess-1",
    source_id: "src-1",
    event_type,
    stage: "connecting",
    severity: "info",
    message: `evento ${event_type}`,
    payload,
    aggregate: Number(payload.count ?? 1) > 1,
    created_at: new Date(Date.now() - seq * 1000).toISOString(),
    ...overrides,
  };
}

function detail(patch: Partial<LearningSessionDetail> = {}): LearningSessionDetail {
  return {
    session_id: "sess-1",
    organization_id: "org-1",
    workspace_id: null,
    title: "Aprendiendo 25 fuentes",
    origin: "upload",
    status: "learning",
    stage: "connecting",
    stage_label: "Conectando",
    stage_technical: "knowledge graph",
    stages: [
      { key: "reading", label: "Leyendo", technical: "parser" },
      { key: "understanding", label: "Entendiendo", technical: "semantic units" },
      { key: "organizing", label: "Organizando", technical: "entity resolution" },
      { key: "connecting", label: "Conectando", technical: "knowledge graph" },
      { key: "verifying", label: "Verificando", technical: "evidence linking" },
      { key: "learned", label: "Aprendido", technical: "indexes" },
    ],
    source_count: 25,
    available_sources: 19,
    completed_sources: 19,
    failed_sources: 0,
    metrics: {},
    knowledge_delta: {},
    delta_totals: {},
    totals_before: {},
    totals_after: {},
    warnings: 0,
    errors: 0,
    started_at: null,
    available_at: null,
    completed_at: null,
    sealed_at: null,
    created_at: null,
    updated_at: null,
    is_available: true,
    sources: [],
    ...patch,
  };
}

describe("taxonomyCounts", () => {
  it("clasifica el delta real en las seis categorías", () => {
    const counts = taxonomyCounts({
      new_entities: 327,
      new_facts: 1842,
      new_relationships: 763,
      new_rules: 96,
      new_evidence: 2418,
      reinforced_facts: 31,
      enriched_entities: 126,
      updated: 3,
      related: 9,
      conflicts: 2,
      ignored: 7,
    });
    expect(counts.new).toBe(5446);
    expect(counts.reinforced).toBe(157);
    expect(counts.updated).toBe(3);
    expect(counts.related).toBe(9);
    expect(counts.conflicting).toBe(2);
    expect(counts.ignored).toBe(7);
  });
});

describe("deriveMilestones", () => {
  it("prioriza conexiones entre conocimiento existente y versiones nuevas", () => {
    const milestones = deriveMilestones(
      [
        event(1, "RELATIONSHIP_DISCOVERED", {
          subject: "ATPCO",
          object: "Pricing interno",
          related: true,
        }),
        event(2, "CONFLICT_DETECTED", {
          conflict_type: "VERSION_CHANGE",
          subject: "Rule 7008",
        }),
        event(3, "ENTITY_MERGED", {
          merged_alias: "Cat 31",
          canonical_name: "Category 31",
        }),
      ],
      detail()
    );
    expect(milestones[0].kind).toBe("connection");
    expect(milestones[0].title).toContain("ATPCO");
    expect(milestones.some((m) => m.kind === "version")).toBe(true);
    expect(milestones.some((m) => m.kind === "merge")).toBe(true);
  });

  it("deduplica por tipo y agrega el cierre de sesión", () => {
    const milestones = deriveMilestones(
      [
        event(1, "CONFLICT_DETECTED", { subject: "A" }),
        event(2, "CONFLICT_DETECTED", { subject: "B" }),
      ],
      detail({ status: "completed", completed_sources: 25 })
    );
    expect(milestones.filter((m) => m.kind === "conflict")).toHaveLength(1);
    expect(milestones.some((m) => m.kind === "completed")).toBe(true);
  });
});

describe("deriveMatches", () => {
  it("cuenta y lista reencuentros sin duplicar nombres", () => {
    const result = deriveMatches([
      event(1, "ENTITY_MATCHED", {
        count: 2,
        items: [{ name: "Record 4", entity_type: "record" }],
      }),
      event(2, "ENTITY_MERGED", {
        merged_alias: "Cat 31",
        canonical_name: "Category 31",
      }),
    ]);
    expect(result.matched).toBe(2);
    expect(result.merged).toBe(1);
    expect(result.matches.map((m) => m.name)).toEqual(["Cat 31", "Record 4"]);
  });
});

describe("deriveStageInsights", () => {
  it("marca estados y solo muestra contadores reales distintos de cero", () => {
    const insights = deriveStageInsights(
      detail().stages,
      {
        pages: 27,
        entities_new: 43,
        facts: 0,
        relationships: 19,
        evidence: 91,
      },
      "connecting",
      false
    );
    expect(insights[0].state).toBe("done");
    expect(insights[3].state).toBe("current");
    expect(insights[5].state).toBe("pending");
    expect(insights[0].items.some((item) => item.label === "páginas")).toBe(true);
    expect(insights[3].items.some((item) => item.label === "relaciones")).toBe(true);
  });
});

describe("deriveRecognizedTables", () => {
  it("lista las tablas reales de la fuente y descarta el agregado", () => {
    const tables = deriveRecognizedTables(
      [
        event(1, "TABLE_DETECTED", { table: "Carrier" }),
        event(2, "TABLE_DETECTED", { table: "Rule" }),
        event(3, "TABLE_DETECTED", { table: "tablas adicionales" }),
        event(4, "TABLE_DETECTED", { table: "Otra" }, { source_id: "src-2" }),
      ],
      "src-1"
    );
    expect(tables).toEqual(["Carrier", "Rule"]);
  });
});

describe("sessionDurationMs", () => {
  it("mide el tiempo real de la sesión", () => {
    const duration = sessionDurationMs(
      detail({
        started_at: "2026-10-03T10:00:00+00:00",
        completed_at: "2026-10-03T10:01:30+00:00",
      })
    );
    expect(duration).toBe(90_000);
  });
});
