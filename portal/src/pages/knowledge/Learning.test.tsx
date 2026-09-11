// =============================================================================
// Learning Studio — tests de estados reales (FASE 33E)
// =============================================================================
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";
import { AuthProvider } from "../../auth";
import { ToastProvider } from "../../Toast";
import KnowledgeLearningPage from "./Learning";

const SOURCE = {
  source_id: "src-1",
  connector_id: "conn-1",
  engine: "postgres",
  connectivity: "healthy",
  phase: "COMPLETED",
  last_learning_at: "2026-09-10T10:00:00Z",
  scan_error: null,
  knowledge: { overall: 82, gate: "NEEDS_INPUT" },
  tables: { analyzed: 42, total: 42 },
  fields: { understood: 352, total: 387, documented: 120 },
  relationships: { discovered: 31, confirmed: 24 },
  pending_questions: 1,
  active_run: null,
};

const STATUS = {
  enabled: true,
  headline: "Zent está aprendiendo cómo funciona tu negocio.",
  counts: {
    sources_connected: 1,
    tables_total: 42,
    columns_total: 387,
    entities_total: 18,
    entities_understood: 18,
    fields_total: 200,
    relationships_total: 31,
    relationships_confirmed: 24,
    pending_questions: 1,
    verified_knowledge: 143,
    open_gaps: 2,
  },
  readiness: { overall: 82, gate: "NEEDS_INPUT", computed_at: null },
  active_runs: [],
  sources: [SOURCE],
};

const SCORE = {
  overall: 82,
  gate: "NEEDS_INPUT",
  dimensions: [
    {
      key: "schema_discovery",
      label: "Descubrimiento de schema",
      score: 100,
      weight: 0.15,
      detail: "42/42 tablas con columnas",
      measured: true,
    },
  ],
  reasons: ["Faltan confirmar 7 relaciones importantes."],
  weights: { schema_discovery: 0.15 },
  computed_at: null,
  source_id: "src-1",
};

const QUESTION = {
  id: "q1",
  source_id: "src-1",
  run_id: "run-1",
  entity_id: "ent-1",
  field_id: null,
  column_id: "col-1",
  question_type: "enum_meaning",
  title: '¿Qué significa CUST_STS = "A", "I" en erp.TBL_CUST?',
  body: "Zent encontró valores categóricos sin significado documentado.",
  evidence: ["valores observados: A (10 filas), I (5 filas)"],
  options: [
    { value: "A", label: "A", occurrence_count: 10 },
    { value: "I", label: "I", occurrence_count: 5 },
  ],
  answer_schema: { kind: "enum_mapping", column_id: "col-1", values: ["A", "I"] },
  priority: "high",
  priority_score: 0.7,
  impact: { retrieval: true },
  status: "pending",
  answer: {},
  structured_answer: {},
  confidence_before: 0.35,
  confidence_after: null,
  created_at: null,
  answered_at: null,
};

const ENTITY = {
  entity_id: "ent-1",
  name: "Customer",
  display_name: "Cliente",
  description: "Personas u organizaciones que compran productos.",
  confidence: 0.94,
  confidence_label: "high",
  provenance: "INFERRED",
  status: "draft",
  table: "erp.TBL_CUST",
  source_id: "src-1",
  fields_total: 12,
  fields_understood: 10,
  columns_total: 12,
  coverage_pct: 83.3,
  relationships_total: 3,
  relationships_confirmed: 2,
  business_rules_total: 2,
  business_rules_approved: 1,
  open_questions: 1,
  last_learned_at: null,
};

const STEP_CONNECTED = {
  id: "step-1",
  stage: "connecting",
  sequence: 0,
  status: "completed",
  progress: 100,
  metrics: {},
  error: null,
  started_at: "2026-09-10T10:00:00Z",
  finished_at: "2026-09-10T10:00:01Z",
  duration_ms: 1200,
};

const STEP_RELATIONS = {
  ...STEP_CONNECTED,
  id: "step-2",
  stage: "detecting_relationships",
  sequence: 1,
  status: "running",
  progress: 0,
  duration_ms: 0,
};

function runFixture(overrides: Record<string, unknown> = {}) {
  return {
    id: "run-1",
    organization_id: "org-1",
    catalog_source_id: "src-1",
    status: "running",
    current_stage: "detecting_relationships",
    overall_progress: 62,
    stage_progress: 0,
    gate: null,
    tables_analyzed: 42,
    entities_detected: 18,
    fields_detected: 200,
    relationships_detected: 31,
    metrics: {},
    error_summary: {},
    created_at: "2026-09-10T10:00:00Z",
    started_at: "2026-09-10T10:00:00Z",
    finished_at: null,
    steps: [STEP_CONNECTED, STEP_RELATIONS],
    ...overrides,
  };
}

function sourceWithRun(run: Record<string, unknown>) {
  return {
    ...SOURCE,
    active_run: {
      id: String(run.id ?? "run-1"),
      status: String(run.status ?? "running"),
      current_stage: String(run.current_stage ?? "connecting"),
      overall_progress: Number(run.overall_progress ?? 0),
    },
  };
}

function json(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

function setupFetch(options: {
  status?: unknown;
  sources?: unknown;
  questions?: unknown;
  run?: unknown;
  answered?: boolean;
}) {
  let answered = options.answered ?? false;
  const calls: Array<{ url: string; method: string; body?: string }> = [];
  const fetchMock = vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input);
    const method = (init?.method || "GET").toUpperCase();
    calls.push({ url, method, body: init?.body as string | undefined });
    if (url.includes("/knowledge/learning/status"))
      return Promise.resolve(json(options.status ?? STATUS));
    if (url.includes("/knowledge/learning/sources"))
      return Promise.resolve(json(options.sources ?? [SOURCE]));
    if (url.includes("/knowledge/learning/score"))
      return Promise.resolve(json(SCORE));
    if (
      url.includes("/knowledge/learning/questions/") &&
      method === "POST" &&
      url.includes("/answer")
    ) {
      answered = true;
      return Promise.resolve(
        json({
          question: { ...QUESTION, status: "answered" },
          applied_to: [{ kind: "enum_meaning" }],
        })
      );
    }
    if (url.includes("/knowledge/learning/questions") && method === "POST") {
      return Promise.resolve(json({ question: QUESTION }));
    }
    if (url.includes("/knowledge/learning/questions")) {
      return Promise.resolve(
        json({
          questions: answered ? [] : (options.questions ?? [QUESTION]),
          count: answered ? 0 : 1,
          pending: answered ? 0 : 1,
          blocking: answered ? 0 : 1,
        })
      );
    }
    if (url.includes("/knowledge/learning/entities"))
      return Promise.resolve(json({ entities: [ENTITY], count: 1 }));
    if (url.includes("/knowledge/learning/events"))
      return Promise.resolve(json({ events: [], count: 0 }));
    if (url.includes("/stream"))
      return Promise.resolve(new Response(null, { status: 204 }));
    if (url.includes("/cancel") && method === "POST")
      return Promise.resolve(json({ cancelled: "run-1" }));
    if (url.includes("/knowledge/learning/start"))
      return Promise.resolve(json({ run: runFixture(), job_id: "job-1" }));
    if (url.includes("/knowledge/learning/runs/")) {
      return Promise.resolve(json(options.run ?? runFixture()));
    }
    if (url.includes("/auth/me"))
      return Promise.resolve(
        json({
          organization_id: "org-1",
          company_name: "Acme",
          email: "a@b.cl",
          roles: ["owner"],
          permissions: [],
        })
      );
    return Promise.resolve(json({ detail: `not mocked: ${url}` }, 500));
  });
  vi.stubGlobal("fetch", fetchMock);
  return { fetchMock, calls, markAnswered: () => (answered = true) };
}

async function renderLearning(options: Parameters<typeof setupFetch>[0] = {}) {
  const harness = setupFetch(options);
  window.localStorage.setItem("rag_portal_token", "rag_sess_t");
  window.localStorage.setItem("rag_portal_org", "org-1");
  window.localStorage.setItem("rag_portal_company", "Acme");
  const user = userEvent.setup();
  render(
    <MemoryRouter initialEntries={["/knowledge/learning"]}>
      <AuthProvider>
        <ToastProvider>
          <KnowledgeLearningPage />
        </ToastProvider>
      </AuthProvider>
    </MemoryRouter>
  );
  return { user, ...harness };
}

afterEach(() => {
  vi.unstubAllGlobals();
  window.localStorage.clear();
  window.sessionStorage.clear();
});

describe("Knowledge Learning Studio", () => {
  it("muestra estado vacío cuando no hay fuentes", async () => {
    await renderLearning({ status: { ...STATUS, counts: { ...STATUS.counts, sources_connected: 0 } }, sources: [] });
    expect(await screen.findByText("Sin fuentes conectadas")).toBeInTheDocument();
  });

  it("muestra readiness, entidades aprendidas y preguntas reales", async () => {
    const awaiting = runFixture({
      status: "awaiting_validation",
      gate: "NEEDS_INPUT",
      overall_progress: 100,
      current_stage: "awaiting_validation",
    });
    await renderLearning({ run: awaiting, sources: [sourceWithRun(awaiting)] });
    expect(await screen.findByTestId("learning-page")).toBeInTheDocument();
    expect((await screen.findAllByText("82%")).length).toBeGreaterThan(0);
    expect(screen.getByText("Cliente")).toBeInTheDocument();
    expect(screen.getByTestId("question-card")).toBeInTheDocument();
    expect(screen.getByText(/valores observados/)).toBeInTheDocument();
    expect(screen.getByText("Zent necesita tu ayuda")).toBeInTheDocument();
  });

  it("responde una pregunta y propaga el conocimiento", async () => {
    const { user, calls, fetchMock } = await renderLearning();
    const card = await screen.findByTestId("question-card");
    expect(card).toBeInTheDocument();

    await user.click(screen.getByTestId("question-option-A"));
    await user.click(screen.getByTestId("question-answer"));

    await waitFor(() => {
      const answerCall = calls.find((call) => call.method === "POST" && call.url.includes("/questions/q1/answer"));
      expect(answerCall).toBeTruthy();
      const body = JSON.parse(answerCall?.body || "{}");
      expect(body.structured_answer.mapping).toEqual({ A: "A", I: "A" });
    });
    expect(await screen.findByText("Zent aprendió")).toBeInTheDocument();
    expect(fetchMock).toHaveBeenCalled();
  });

  it("permite descartar y diferir preguntas", async () => {
    const { user, calls } = await renderLearning();
    await screen.findByTestId("question-card");
    await user.click(screen.getByTestId("question-skip"));
    await waitFor(() =>
      expect(
        calls.some((call) => call.url.includes("/questions/q1/skip"))
      ).toBe(true)
    );
    await user.click(screen.getByTestId("question-defer"));
    await waitFor(() =>
      expect(
        calls.some((call) => call.url.includes("/questions/q1/defer"))
      ).toBe(true)
    );
  });

  it("muestra progreso y timeline reales durante un run", async () => {
    const running = runFixture();
    await renderLearning({ run: running, sources: [sourceWithRun(running)] });
    expect(await screen.findByTestId("learning-orb")).toBeInTheDocument();
    expect(await screen.findByTestId("learning-progress")).toBeInTheDocument();
    expect(screen.getByText("62%")).toBeInTheDocument();
    expect(screen.getByTestId("learning-timeline")).toBeInTheDocument();
    expect(screen.getByText("Entendiendo relaciones...")).toBeInTheDocument();
  });

  it("muestra el error de un run fallido", async () => {
    const failed = runFixture({
      status: "failed",
      current_stage: "connecting",
      overall_progress: 5,
      error_summary: { error: "ConnectorError: no se pudo conectar" },
    });
    await renderLearning({ run: failed, sources: [sourceWithRun(failed)] });
    expect((await screen.findAllByText("El aprendizaje falló")).length).toBeGreaterThan(0);
    expect(screen.getByText(/no se pudo conectar/)).toBeInTheDocument();
  });

  it("un 401 no deja el Studio a medias con ErrorInline y limpia la sesión", async () => {
    const fetchMock = vi.fn((input: RequestInfo | URL) => {
      const url = String(input);
      if (url.includes("/auth/me")) {
        return Promise.resolve(
          json({
            organization_id: "org-1",
            company_name: "Acme",
            email: "a@b.cl",
            roles: ["owner"],
            permissions: [],
          })
        );
      }
      if (url.includes("/knowledge/learning/")) {
        return Promise.resolve(json({ detail: "expired" }, 401));
      }
      return Promise.resolve(json({ detail: `not mocked: ${url}` }, 500));
    });
    vi.stubGlobal("fetch", fetchMock);
    window.localStorage.setItem("rag_portal_token", "rag_sess_t");
    window.localStorage.setItem("rag_portal_org", "org-1");
    window.localStorage.setItem("rag_portal_company", "Acme");

    render(
      <MemoryRouter initialEntries={["/knowledge/learning"]}>
        <AuthProvider>
          <ToastProvider>
            <KnowledgeLearningPage />
          </ToastProvider>
        </AuthProvider>
      </MemoryRouter>
    );

    await waitFor(() => {
      expect(window.localStorage.getItem("rag_portal_org")).toBeNull();
    });
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    expect(screen.queryByTestId("learning-page")).not.toBeInTheDocument();
    expect(screen.queryByText(/No se pudo cargar/)).not.toBeInTheDocument();
    expect(screen.queryByText("Sin fuentes conectadas")).not.toBeInTheDocument();
  });

  it("cancela un run en curso", async () => {
    const running = runFixture();
    const { user, calls } = await renderLearning({
      run: running,
      sources: [sourceWithRun(running)],
    });
    await screen.findByTestId("run-cancel");
    await user.click(screen.getByTestId("run-cancel"));
    await waitFor(() =>
      expect(
        calls.some(
          (call) => call.method === "POST" && call.url.includes("/cancel")
        )
      ).toBe(true)
    );
    expect(await screen.findByText("Aprendizaje cancelado")).toBeInTheDocument();
  });
});
