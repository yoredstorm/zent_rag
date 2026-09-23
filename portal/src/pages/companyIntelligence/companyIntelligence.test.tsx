import { render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";
import CompanyOverviewPage from "./Overview";
import CompanyKnowledgeGapsPage from "./KnowledgeGaps";
import CompanySourceAuthorityPage from "./SourceAuthority";
import CompanyAskPage from "./Ask";
import CompanyMapPage from "./CompanyMap";
import CompanyEntityDetailPage from "./EntityDetail";
import CompanyInstitutionalPage from "./Institutional";

const AUTH = vi.hoisted(() => ({
  session: {
    token: "rag_sess_t",
    organizationId: "org-1",
    roles: ["owner"],
    permissions: [],
  },
}));

vi.mock("../../auth", () => ({ useAuth: () => AUTH }));

function json(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

function stubApi(handlers: Array<[string, unknown]>) {
  vi.stubGlobal(
    "fetch",
    vi.fn((input: RequestInfo | URL) => {
      const url = String(input);
      for (const [fragment, body] of handlers) {
        if (url.includes(fragment)) return Promise.resolve(json(body));
      }
      return Promise.resolve(json({}));
    }),
  );
}

afterEach(() => {
  vi.unstubAllGlobals();
});

const OVERVIEW = {
  entities: {
    total: 13,
    by_status: { confirmed: 11, discovered: 2 },
    by_type: { concept: 1, system: 1, table: 1 },
    confirmed: 11,
    discovered: 2,
    contradicted: 0,
    stale: 0,
  },
  relationships: { total: 12, confirmed: 10, by_status: { confirmed: 10 } },
  knowledge_gaps: { total: 2, by_kind: { undocumented_step: 1, missing_process_owner: 1 } },
  potential_risks: 1,
  coverage: {
    concepts: 1,
    processes: 2,
    systems: 1,
    datasets: 1,
    tables: 1,
    rules: 1,
    agents: 1,
    workflows: 1,
    knowledge_sources: 1,
  },
  discovery: { available: true, total: 1 },
  as_of: new Date().toISOString(),
};

describe("CompanyOverviewPage", () => {
  it("muestra conteos reales del grafo y huecos de conocimiento", async () => {
    stubApi([
      ["/company-intelligence/overview", OVERVIEW],
      ["/company-intelligence/risks", { items: [] }],
      ["/company-intelligence/changes", { items: [], since: new Date().toISOString() }],
    ]);
    render(
      <MemoryRouter initialEntries={["/company-intelligence"]}>
        <CompanyOverviewPage />
      </MemoryRouter>,
    );
    await waitFor(() => expect(screen.getByText("Conceptos")).toBeTruthy());
    expect(screen.getByText("Huecos de conocimiento")).toBeTruthy();
    // Los huecos se muestran por tipo, con etiqueta legible.
    expect(screen.getByText("Paso sin documentar")).toBeTruthy();
    // El estado del grafo se muestra con texto, no sólo color.
    expect(screen.getByText(/Confirmado · 11/)).toBeTruthy();
  });

  it("muestra riesgos marcados como potenciales", async () => {
    stubApi([
      ["/company-intelligence/overview", OVERVIEW],
      [
        "/company-intelligence/risks",
        {
          items: [
            {
              risk_kind: "single_dependency",
              level: "potential",
              entity_id: "e-1",
              entity: "Fare Audit",
              entity_type: "process",
              detail: "Fare Audit depends on a single system: PXSAUDIT",
            },
          ],
        },
      ],
      ["/company-intelligence/changes", { items: [], since: new Date().toISOString() }],
    ]);
    render(
      <MemoryRouter initialEntries={["/company-intelligence"]}>
        <CompanyOverviewPage />
      </MemoryRouter>,
    );
    await waitFor(() => expect(screen.getByTestId("risk-list")).toBeTruthy());
    expect(screen.getByText("Potencial")).toBeTruthy();
  });
});

describe("CompanyKnowledgeGapsPage", () => {
  it("lista huecos con su tipo y origen", async () => {
    stubApi([
      [
        "/company-intelligence/knowledge-gaps",
        {
          items: [
            {
              id: "g-1",
              gap_kind: "undocumented_step",
              subject: "Reconciliation Process:manual-review",
              detail: "step occurs in 27% of runs but is not documented",
              frequency: 0.27,
              observed_runs: 100,
              stage: "suggested",
              origin: "discovery",
            },
            {
              gap_kind: "no_authoritative_definition",
              subject: "Ticket Status",
              detail: "Ticket Status has no authoritative source configured",
              origin: "graph",
            },
          ],
          by_kind: { undocumented_step: 1, no_authoritative_definition: 1 },
        },
      ],
    ]);
    render(
      <MemoryRouter initialEntries={["/company-intelligence/gaps"]}>
        <CompanyKnowledgeGapsPage />
      </MemoryRouter>,
    );
    await waitFor(() => expect(screen.getByTestId("gap-list")).toBeTruthy());
    const list = within(screen.getByTestId("gap-list"));
    expect(list.getByText("Paso sin documentar")).toBeTruthy();
    expect(list.getByText(/27% de/)).toBeTruthy();
    expect(list.getByText(/origen: grafo/)).toBeTruthy();
  });
});

describe("CompanySourceAuthorityPage", () => {
  it("muestra autoritativa, secundaria y conceptos sin autoridad", async () => {
    stubApi([
      [
        "/company-intelligence/source-of-truth",
        {
          items: [
            {
              concept_id: "c-1",
              concept: "Pending Transaction",
              domain: "fare-audit",
              authoritative: [
                { source_name: "PXSAUDIT", source_type: "database", authority_level: "authoritative", priority: 1 },
              ],
              primary: [],
              secondary: [
                { source_name: "documentation", source_type: "document", authority_level: "secondary", priority: 1 },
              ],
              informational: [],
              sources: [
                { source_name: "PXSAUDIT", source_type: "database", authority_level: "authoritative", priority: 1 },
              ],
              has_authority: true,
            },
          ],
          conflicts: [],
          concepts_without_authority: [],
        },
      ],
    ]);
    render(
      <MemoryRouter initialEntries={["/company-intelligence/authority"]}>
        <CompanySourceAuthorityPage />
      </MemoryRouter>,
    );
    await waitFor(() => expect(screen.getByTestId("authority-entry")).toBeTruthy());
    expect(screen.getByText("Autoritativa")).toBeTruthy();
    expect(screen.getByText("Secundaria")).toBeTruthy();
  });
});

describe("CompanyAskPage", () => {
  it("responde con evidencia y declara el proveedor de juicio", async () => {
    stubApi([
      ["/ask/examples", { items: ["¿Qué proceso usa A1672?"] }],
      [
        "/company-intelligence/ask",
        {
          question: "¿Dónde se representa Carrier Code?",
          intent: "representation",
          answer: "Dónde se representa Carrier Code:\n- field A1672STO0 (valores: 0)",
          certainty: "confirmed",
          decision: { provider: "lexical", intent: "representation", confidence: 0.6, fallback_used: true, reason: "judge_unavailable" },
          evidence: [
            { kind: "mapping", ref: "e-2", label: "A1672STO0 (field)", detail: { status: "confirmed" } },
          ],
          context_used: { tokens_estimate: 240, truncated: false, concepts: 1, mappings: 1, processes: 0, systems: 0, memories: 0 },
          followups: ["¿Qué fuente manda sobre ella?"],
        },
      ],
    ]);
    render(
      <MemoryRouter initialEntries={["/company-intelligence/ask"]}>
        <CompanyAskPage />
      </MemoryRouter>,
    );
    await waitFor(() => expect(screen.getByTestId("company-ask-input")).toBeTruthy());
    const { default: userEvent } = await import("@testing-library/user-event");
    const user = userEvent.setup();
    await user.type(
      screen.getByRole("textbox"),
      "¿Dónde se representa Carrier Code?",
    );
    await user.click(screen.getByRole("button", { name: /Preguntar/i }));
    await waitFor(() => expect(screen.getByTestId("company-answer")).toBeTruthy());
    expect(screen.getByTestId("company-evidence")).toBeTruthy();
    expect(screen.getByText(/router determinista/i)).toBeTruthy();
    expect(screen.getByText(/240/)).toBeTruthy();
  });
});

describe("CompanyMapPage", () => {
  it("expande una entidad y muestra relaciones con su estado", async () => {
    stubApi([
      [
        "/company-intelligence/entities",
        {
          items: [
            {
              id: "e-1",
              entity_type: "table",
              canonical_name: "A1672",
              display_name: "A1672",
              status: "confirmed",
              confidence: 0.9,
              authority_level: null,
            },
          ],
        },
      ],
      [
        "/company-intelligence/map/e-1",
        {
          root: {
            id: "e-1",
            entity_type: "table",
            canonical_name: "A1672",
            display_name: "A1672",
            status: "confirmed",
            confidence: 0.9,
            authority_level: null,
          },
          nodes: [
            {
              id: "e-2",
              entity_type: "system",
              canonical_name: "PXSAUDIT",
              display_name: "PXSAUDIT",
              status: "confirmed",
              confidence: 0.9,
              authority_level: null,
            },
            {
              id: "e-3",
              entity_type: "field",
              canonical_name: "A1672STO0",
              display_name: "A1672STO0",
              status: "discovered",
              confidence: 0.4,
              authority_level: null,
            },
          ],
          edges: [
            {
              id: "r-1",
              relationship_type: "BELONGS_TO",
              direction: "outgoing",
              from: { id: "e-1", name: "A1672", type: "table" },
              to: { id: "e-2", name: "PXSAUDIT", type: "system" },
              status: "confirmed",
              confidence: 0.9,
              source: "manual",
              valid_from: null,
              valid_to: null,
              confirmed: true,
            },
            {
              id: "r-2",
              relationship_type: "CONTAINS",
              direction: "outgoing",
              from: { id: "e-1", name: "A1672", type: "table" },
              to: { id: "e-3", name: "A1672STO0", type: "field" },
              status: "discovered",
              confidence: 0.4,
              source: "database_schema",
              valid_from: null,
              valid_to: null,
              confirmed: false,
            },
          ],
          groups: { systems: [], data: [] },
          truncated: false,
          limits: { max_nodes: 15, max_edges: 60, max_depth: 1 },
        },
      ],
    ]);
    render(
      <MemoryRouter initialEntries={["/company-intelligence/map?entity=e-1"]}>
        <CompanyMapPage />
      </MemoryRouter>,
    );
    await waitFor(() => expect(screen.getByTestId("company-map-canvas")).toBeTruthy());
    const edges = within(screen.getByTestId("edge-list"));
    expect(edges.getByText("BELONGS_TO")).toBeTruthy();
    expect(edges.getByText("CONTAINS")).toBeTruthy();
    // La relación no confirmada se declara como tal, no como verdad.
    expect(edges.getByText("(no confirmada)")).toBeTruthy();
    expect(edges.getByText("Descubierto")).toBeTruthy();
  });
});

describe("CompanyEntityDetailPage", () => {
  it("muestra el detalle con relaciones y mapeos, distinguiendo no confirmadas", async () => {
    stubApi([
      [
        "/company-intelligence/entities/e-1",
        {
          entity: {
            id: "e-1",
            entity_type: "concept",
            canonical_name: "Pending Transaction",
            display_name: "Pending Transaction",
            description: "Transacción no procesada",
            domain: "fare-audit",
            status: "confirmed",
            confidence: 0.9,
            authority_level: "authoritative",
            aliases: ["pending"],
            valid_from: null,
            valid_to: null,
            last_observed_at: new Date().toISOString(),
          },
          incoming: [
            {
              id: "r-1",
              relationship_type: "USES",
              direction: "incoming",
              from: { id: "e-9", name: "Audit Agent", type: "agent" },
              to: { id: "e-1", name: "Pending Transaction", type: "concept" },
              status: "confirmed",
              confidence: 0.8,
              source: "manual",
              valid_from: null,
              valid_to: null,
              confirmed: true,
            },
          ],
          outgoing: [
            {
              id: "r-2",
              relationship_type: "MAPS_TO",
              direction: "outgoing",
              from: { id: "e-1", name: "Pending Transaction", type: "concept" },
              to: { id: "e-2", name: "A1672STO0", type: "field" },
              status: "discovered",
              confidence: 0.5,
              source: "sql_usage",
              valid_from: null,
              valid_to: null,
              confirmed: false,
            },
          ],
          related: {
            automation: [
              { id: "e-9", display_name: "Audit Agent", entity_type: "agent", status: "confirmed" },
            ],
          },
          technical_mappings: [
            {
              id: "r-2",
              target: "A1672STO0",
              target_type: "field",
              values: ["0", ""],
              predicate: "A1672STO0 IN ('0', '')",
              status: "discovered",
              confidence: 0.5,
            },
          ],
          authority: [
            { source_name: "PXSAUDIT", authority_level: "authoritative", source_type: "database" },
          ],
          memory: [],
          knowledge_gaps: [],
        },
      ],
    ]);
    render(
      <MemoryRouter initialEntries={["/company-intelligence/entity/e-1"]}>
        <Routes>
          <Route
            path="/company-intelligence/entity/:entityId"
            element={<CompanyEntityDetailPage />}
          />
        </Routes>
      </MemoryRouter>,
    );
    await waitFor(() => expect(screen.getByTestId("mapping-list")).toBeTruthy());
    expect(screen.getByText("Pending Transaction")).toBeTruthy();
    expect(screen.getByText(/valores: 0/)).toBeTruthy();
    expect(screen.getByText(/Autoridad: authoritative/)).toBeTruthy();
  });
});

describe("CompanyInstitutionalPage", () => {
  it("muestra responsables y procesos sin dueño", async () => {
    stubApi([
      [
        "/company-intelligence/institutional",
        {
          people: [],
          roles: [],
          teams: [
            { id: "t-1", display_name: "Audit Team", entity_type: "team", status: "confirmed" },
          ],
          process_ownership: [
            {
              process_id: "p-1",
              process: "Reconciliation Process",
              owners: [
                {
                  owner_id: "t-1",
                  owner: "Audit Team",
                  owner_type: "team",
                  relationship_type: "OWNS",
                  status: "confirmed",
                },
              ],
            },
          ],
          processes_without_owner: ["Fare Audit"],
        },
      ],
    ]);
    render(
      <MemoryRouter initialEntries={["/company-intelligence/people"]}>
        <CompanyInstitutionalPage />
      </MemoryRouter>,
    );
    await waitFor(() => expect(screen.getByTestId("process-ownership")).toBeTruthy());
    const ownership = within(screen.getByTestId("process-ownership"));
    expect(ownership.getByText("Audit Team")).toBeTruthy();
    expect(ownership.getByText("Reconciliation Process")).toBeTruthy();
    expect(screen.getByText("Fare Audit")).toBeTruthy();
  });
});
