// =============================================================================
// Knowledge Session UI — la información mostrada sale de eventos reales
// =============================================================================
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import type { LearningSessionDetail, SessionEvent } from "../../lib/knowledgeSessions";
import { DiscoveryFeed } from "./DiscoveryFeed";
import { KnowledgePulse } from "./KnowledgePulse";
import { LearningSummary } from "./LearningSummary";
import { deriveDelta, deriveMetrics, groupDiscoveries } from "./useLearningSession";

function event(
  seq: number,
  event_type: string,
  payload: Record<string, unknown> = {},
  overrides: Partial<SessionEvent> = {},
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
    aggregate: (payload.count as number) > 1,
    created_at: new Date(Date.now() - 4000).toISOString(),
    ...overrides,
  };
}

describe("deriveMetrics", () => {
  it("suma solo eventos reales y respeta payload.count", () => {
    const metrics = deriveMetrics([
      event(1, "ENTITY_DISCOVERED", { count: 3 }),
      event(2, "ENTITY_MATCHED", { count: 2 }),
      event(3, "FACT_DISCOVERED", { count: 7 }),
      event(4, "EVIDENCE_LINKED", { count: 12 }),
      event(5, "SOURCE_RECEIVED", { name: "x.pdf" }),
    ]);
    expect(metrics.entities_new).toBe(3);
    expect(metrics.entities_enriched).toBe(2);
    expect(metrics.entities).toBe(5);
    expect(metrics.facts).toBe(7);
    expect(metrics.evidence).toBe(12);
    expect(metrics.relationships ?? 0).toBe(0);
  });
});

describe("deriveDelta", () => {
  it("separa nuevo, reforzado, actualizado y conflictivo", () => {
    const delta = deriveDelta([
      event(1, "ENTITY_DISCOVERED", { count: 4 }),
      event(2, "FACT_DISCOVERED", { count: 9 }),
      event(3, "FACT_REINFORCED", { count: 2 }),
      event(4, "RELATIONSHIP_DISCOVERED", { related: true }),
      event(5, "CONFLICT_DETECTED", { conflict_type: "VERSION_CHANGE" }),
      event(6, "CONFLICT_DETECTED", { conflict_type: "SOURCE_CONFLICT" }),
      event(7, "DUPLICATE_DETECTED", { count: 2 }),
    ]);
    expect(delta.new_entities).toBe(4);
    expect(delta.new_facts).toBe(9);
    expect(delta.reinforced_facts).toBe(2);
    expect(delta.new_relationships).toBe(1);
    expect(delta.related).toBe(1);
    expect(delta.updated).toBe(1);
    expect(delta.conflicts).toBe(1);
    expect(delta.ignored).toBe(2);
  });
});

describe("groupDiscoveries", () => {
  it("agrupa consecutivos del mismo tipo y oculta el ruido de pipeline", () => {
    const discoveries = groupDiscoveries([
      event(1, "SOURCE_RECEIVED", { name: "Rec4.pdf" }),
      event(2, "ENTITY_DISCOVERED", { count: 20, items: [{ name: "Record 4" }] }),
      event(3, "ENTITY_DISCOVERED", { count: 4, items: [{ name: "Category 31" }] }),
      event(4, "CONFLICT_DETECTED", { subject: "Carrier Code" }, { severity: "warning" }),
    ]);
    expect(discoveries.some((item) => item.event_type === "SOURCE_RECEIVED")).toBe(false);
    const entityItems = discoveries.filter((item) => item.event_type === "ENTITY_DISCOVERED");
    expect(entityItems).toHaveLength(1);
    expect(entityItems[0].count).toBe(24);
    // El feed se lee de lo más reciente a lo más antiguo.
    expect(discoveries[0].event_type).toBe("CONFLICT_DETECTED");
  });
});

describe("KnowledgePulse", () => {
  it("muestra los contadores reales y el estado de aprendizaje", () => {
    render(
      <KnowledgePulse
        metrics={{ entities: 286, relationships: 731, facts: 1428, rules: 119, evidence: 2094 }}
        sources={[
          {
            id: "s1",
            session_id: "sess-1",
            source_id: "src-1",
            job_id: "job-1",
            name: "Record 4 – Renumber Control",
            source_type: "file",
            status: "learning",
            stage: "connecting",
            stage_label: "Conectando",
            stats: {},
            error: null,
            available_at: null,
            completed_at: null,
            created_at: null,
            updated_at: null,
          },
        ]}
        stageLabel="Conectando"
        active
      />,
    );
    expect(screen.getByTestId("knowledge-pulse")).toBeInTheDocument();
    expect(screen.getByText("ZENT está aprendiendo")).toBeInTheDocument();
    expect(screen.getByText("286")).toBeInTheDocument();
    expect(screen.getByText(/2[.,]094/)).toBeInTheDocument();
    expect(screen.getByText("Record 4 – Renumber Control")).toBeInTheDocument();
  });
});

describe("DiscoveryFeed", () => {
  it("expande un descubrimiento para ver el detalle real", async () => {
    const user = userEvent.setup();
    render(
      <DiscoveryFeed
        discoveries={groupDiscoveries([
          event(1, "ENTITY_MATCHED", { count: 1, name: "Record 4", entity_type: "record", items: [{ name: "Record 4", entity_type: "record" }] }),
        ])}
        sources={[]}
      />,
    );
    await user.click(screen.getByRole("button"));
    const feed = within(screen.getByTestId("discovery-feed"));
    expect(feed.getByText("Record 4")).toBeInTheDocument();
    expect(feed.getByText("record")).toBeInTheDocument();
  });
});

describe("LearningSummary", () => {
  it("prioriza el delta y muestra antes/después", () => {
    const detail = {
      session_id: "sess-1",
      organization_id: "org-1",
      workspace_id: null,
      title: "Aprendiendo 14 fuentes",
      origin: "upload",
      status: "completed",
      stage: "learned",
      stage_label: "Aprendido",
      stage_technical: "indexes",
      stages: [],
      source_count: 14,
      available_sources: 14,
      completed_sources: 14,
      failed_sources: 0,
      metrics: {},
      knowledge_delta: {},
      delta_totals: {},
      totals_before: { entities: 18204, relationships: 71321, facts: 139822 },
      totals_after: { entities: 18616, relationships: 72084, facts: 141664 },
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
    } as LearningSessionDetail;

    render(
      <LearningSummary
        detail={detail}
        delta={{
          new_entities: 412,
          new_facts: 1842,
          new_relationships: 763,
          new_rules: 96,
          new_evidence: 2418,
          enriched_entities: 126,
          reinforced_facts: 31,
          duplicates: 7,
          conflicts: 2,
          updated: 0,
          related: 0,
          ignored: 0,
        }}
      />,
    );
    expect(screen.getByText("ZENT aprendió esta información")).toBeInTheDocument();
    const beforeAfter = screen.getByTestId("before-after");
    expect(within(beforeAfter).getByText("+412")).toBeInTheDocument();
    expect(within(beforeAfter).getByText(/\+1[.,]842/)).toBeInTheDocument();
    expect(screen.getByTestId("learning-taxonomy")).toBeInTheDocument();
  });
});
