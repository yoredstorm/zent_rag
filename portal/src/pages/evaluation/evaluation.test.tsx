import type { ReactNode } from "react";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { Session } from "../../api";
import { AuthProvider } from "../../auth";
import { EvalCaseDialog } from "../../components/evaluation/EvalCaseDialog";
import DatasetsPage from "./Datasets";
import RunDetailPage from "./RunDetail";
import RunsPage from "./Runs";

const SESSION = {
  token: "rag_sess_t",
  organizationId: "org-1",
  companyName: "Acme",
  roles: ["owner"],
  permissions: [],
} as Session;

function json(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

function authShell(ui: ReactNode) {
  window.localStorage.setItem("rag_portal_token", "rag_sess_t");
  window.localStorage.setItem("rag_portal_org", "org-1");
  window.localStorage.setItem("rag_portal_company", "Acme");
  return <AuthProvider>{ui}</AuthProvider>;
}

function meResponse() {
  return json({
    organization_id: "org-1",
    company_name: "Acme",
    email: "a@b.cl",
    roles: ["owner"],
    permissions: [],
  });
}

function findPost(
  fetchMock: ReturnType<typeof vi.fn>,
  urlPart: string,
  method = "POST",
): { body: Record<string, unknown> } | null {
  const call = fetchMock.mock.calls.find(
    ([url, init]) =>
      String(url).includes(urlPart) &&
      String((init as RequestInit | undefined)?.method || "GET").toUpperCase() === method,
  );
  if (!call) return null;
  const init = call[1] as RequestInit | undefined;
  return { body: JSON.parse(String(init?.body || "{}")) };
}

afterEach(() => {
  vi.unstubAllGlobals();
  window.localStorage.clear();
  window.sessionStorage.clear();
});

describe("Evaluación · runs", () => {
  it("permite elegir el agente como objetivo del run", async () => {
    const fetchMock = vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      const method = (init?.method || "GET").toUpperCase();
      if (url.includes("/auth/me")) return Promise.resolve(meResponse());
      if (url.includes("/api/v1/eval/runs") && method === "POST")
        return Promise.resolve(json({ run_id: "r1" }));
      if (url.includes("/api/v1/eval/runs")) return Promise.resolve(json({ runs: [] }));
      if (url.includes("/api/v1/eval/datasets"))
        return Promise.resolve(json({ datasets: [{ id: "d1", name: "cat31", case_count: 1 }] }));
      if (url.includes("/api/v1/agents"))
        return Promise.resolve(
          json({ agents: [{ id: "a1", name: "ATPCO", status: "active" }] }),
        );
      return Promise.resolve(json({ detail: "not mocked: " + url }, 500));
    });
    vi.stubGlobal("fetch", fetchMock);
    const user = userEvent.setup();

    render(
      <MemoryRouter initialEntries={["/evaluation/runs"]}>
        {authShell(
          <Routes>
            <Route path="/evaluation/runs" element={<RunsPage />} />
          </Routes>,
        )}
      </MemoryRouter>,
    );

    await screen.findByRole("option", { name: "Agente · ATPCO" });
    await user.selectOptions(screen.getByLabelText("Dataset"), "d1");
    await user.selectOptions(screen.getByLabelText("Objetivo"), "a1");
    await user.click(screen.getByRole("button", { name: "Lanzar" }));

    await waitFor(() => {
      const post = findPost(fetchMock, "/api/v1/eval/runs");
      expect(post).not.toBeNull();
      expect(post?.body.target_type).toBe("agent");
      expect(post?.body.target_id).toBe("a1");
      expect(post?.body.dataset_id).toBe("d1");
    });
  });

  it("muestra el objetivo del run en la lista", async () => {
    const fetchMock = vi.fn((input: RequestInfo | URL) => {
      const url = String(input);
      if (url.includes("/auth/me")) return Promise.resolve(meResponse());
      if (url.includes("/api/v1/eval/runs"))
        return Promise.resolve(
          json({
            runs: [
              {
                id: "r1",
                dataset_name: "cat31",
                target_type: "agent",
                target_name: "ATPCO",
                status: "completed",
                created_at: "2026-09-29T04:39:00Z",
                quality: { composite_score: 0.1 },
              },
              {
                id: "r2",
                dataset_name: "base",
                target_type: "rag",
                target_name: "rag-pipeline",
                status: "completed",
                created_at: "2026-09-29T04:30:00Z",
                quality: { composite_score: 0.9 },
              },
            ],
          }),
        );
      if (url.includes("/api/v1/eval/datasets")) return Promise.resolve(json({ datasets: [] }));
      if (url.includes("/api/v1/agents")) return Promise.resolve(json({ agents: [] }));
      return Promise.resolve(json({ detail: "not mocked: " + url }, 500));
    });
    vi.stubGlobal("fetch", fetchMock);

    render(
      <MemoryRouter initialEntries={["/evaluation/runs"]}>
        {authShell(
          <Routes>
            <Route path="/evaluation/runs" element={<RunsPage />} />
          </Routes>,
        )}
      </MemoryRouter>,
    );

    expect(await screen.findByText("ATPCO")).toBeInTheDocument();
    expect(screen.getByText("Pipeline RAG")).toBeInTheDocument();
  });
});

describe("Evaluación · dataset sin JSON", () => {
  it("crea el dataset en el momento si no existe", async () => {
    const fetchMock = vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      const method = (init?.method || "GET").toUpperCase();
      if (url.includes("/api/v1/eval/datasets") && method === "POST")
        return Promise.resolve(json({ dataset_id: "d9", name: "Nuevo" }, 201));
      if (url.includes("/api/v1/eval/datasets/d9/examples") && method === "POST")
        return Promise.resolve(json({ inserted: [], count: 1 }, 201));
      if (url.includes("/api/v1/eval/datasets"))
        return Promise.resolve(json({ datasets: [] }));
      return Promise.resolve(json({ detail: "not mocked: " + url }, 500));
    });
    vi.stubGlobal("fetch", fetchMock);
    const user = userEvent.setup();

    render(
      <EvalCaseDialog open onOpenChange={() => {}} session={SESSION} />,
    );

    await screen.findByRole("option", { name: "＋ Nuevo dataset" });
    await user.type(screen.getByLabelText("Nombre del nuevo dataset"), "Recién creado");
    await user.type(screen.getByLabelText("Pregunta"), "¿Qué es la categoría 31?");
    await user.click(screen.getByRole("button", { name: "Agregar caso" }));

    await waitFor(() => {
      const datasetPost = findPost(fetchMock, "/api/v1/eval/datasets");
      expect(datasetPost?.body.name).toBe("Recién creado");
      const casePost = findPost(fetchMock, "/api/v1/eval/datasets/d9/examples");
      expect(casePost).not.toBeNull();
      const examples = casePost?.body.examples as { question: string }[];
      expect(examples[0].question).toBe("¿Qué es la categoría 31?");
    });
  });

  it("agrega un caso con el formulario y su comportamiento", async () => {
    const fetchMock = vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      const method = (init?.method || "GET").toUpperCase();
      if (url.includes("/auth/me")) return Promise.resolve(meResponse());
      if (url.includes("/examples") && method === "POST")
        return Promise.resolve(json({ inserted: [], count: 1 }, 201));
      if (url.includes("/api/v1/eval/datasets"))
        return Promise.resolve(
          json({ datasets: [{ id: "d1", name: "cat31", case_count: 0 }] }),
        );
      return Promise.resolve(json({ detail: "not mocked: " + url }, 500));
    });
    vi.stubGlobal("fetch", fetchMock);
    const user = userEvent.setup();

    render(
      <MemoryRouter initialEntries={["/evaluation/datasets"]}>
        {authShell(
          <Routes>
            <Route path="/evaluation/datasets" element={<DatasetsPage />} />
          </Routes>,
        )}
      </MemoryRouter>,
    );

    await screen.findByText("cat31");
    await user.click(screen.getByRole("button", { name: "Agregar caso" }));
    const dialog = await screen.findByRole("dialog");
    await user.type(within(dialog).getByLabelText("Pregunta"), "¿Qué es la categoría 31?");
    await user.selectOptions(
      within(dialog).getByLabelText("Comportamiento esperado"),
      "abstain",
    );
    await user.click(within(dialog).getByRole("button", { name: "Agregar caso" }));

    await waitFor(() => {
      const post = findPost(fetchMock, "/api/v1/eval/datasets/d1/examples");
      expect(post).not.toBeNull();
      const examples = post?.body.examples as { question: string; expected_behavior: string }[];
      expect(examples[0].question).toBe("¿Qué es la categoría 31?");
      expect(examples[0].expected_behavior).toBe("abstain");
    });
  });

  it("gestiona el dataset: renombra y elimina casos", async () => {
    const fetchMock = vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      const method = (init?.method || "GET").toUpperCase();
      if (url.includes("/auth/me")) return Promise.resolve(meResponse());
      if (url.includes("/api/v1/eval/datasets/d1/examples/e1") && method === "DELETE")
        return Promise.resolve(json({ status: "deleted" }));
      if (url.includes("/api/v1/eval/datasets/d1/examples"))
        return Promise.resolve(
          json({
            examples: [
              {
                id: "e1",
                question: "pregunta vieja",
                expected_answer: null,
                expected_behavior: "abstain",
                expected_sources: ["Cat31.pdf"],
              },
            ],
            count: 1,
          }),
        );
      if (url.includes("/api/v1/eval/datasets/d1") && method === "PATCH")
        return Promise.resolve(json({ status: "renamed" }));
      if (url.includes("/api/v1/eval/datasets"))
        return Promise.resolve(
          json({ datasets: [{ id: "d1", name: "cat31", case_count: 1 }] }),
        );
      return Promise.resolve(json({ detail: "not mocked: " + url }, 500));
    });
    vi.stubGlobal("fetch", fetchMock);
    const user = userEvent.setup();

    render(
      <MemoryRouter initialEntries={["/evaluation/datasets"]}>
        {authShell(
          <Routes>
            <Route path="/evaluation/datasets" element={<DatasetsPage />} />
          </Routes>,
        )}
      </MemoryRouter>,
    );

    await screen.findByText("cat31");
    await user.click(screen.getByRole("button", { name: "Gestionar" }));
    const dialog = await screen.findByRole("dialog");
    expect(await within(dialog).findByText("pregunta vieja")).toBeInTheDocument();

    const nameInput = within(dialog).getByLabelText("Nombre del dataset");
    await user.clear(nameInput);
    await user.type(nameInput, "cat31 v2");
    await user.click(within(dialog).getByRole("button", { name: "Guardar nombre" }));
    await waitFor(() => {
      const patch = findPost(fetchMock, "/api/v1/eval/datasets/d1", "PATCH");
      expect(patch?.body.name).toBe("cat31 v2");
    });

    await user.click(within(dialog).getByRole("button", { name: "Eliminar" }));
    await waitFor(() => {
      expect(
        fetchMock.mock.calls.some(
          ([url, init]) =>
            String(url).includes("/examples/e1") &&
            String((init as RequestInit | undefined)?.method || "").toUpperCase() ===
              "DELETE",
        ),
      ).toBe(true);
    });
  });
});

describe("Evaluación · detalle del run", () => {
  it("explica la abstención y el objetivo del run", async () => {
    const run = {
      run_id: "r1",
      dataset_name: "cat31",
      target_type: "agent",
      target_name: "ATPCO",
      created_at: "2026-09-29T04:39:00Z",
      total_cases: 1,
      failed_cases: 0,
      quality: {
        composite_score: 0.1,
        faithfulness: 0.0,
        hallucination_rate: 1.0,
        judge_enabled: false,
      },
      performance: { latency: { avg_ms: 3000, count: 1 } },
      cases: [
        {
          case_id: "case-001",
          question: "explicame la categoria 31",
          answer: "La evidencia recopilada no alcanza el umbral.",
          expected_answer: null,
          expected_sources: [],
          status: "completed",
          scores: { composite: 0.1, faithfulness: 0.0 },
          metrics: {
            answerability_status: "HUMAN_REVIEW_REQUIRED",
            expected_answerability: "HUMAN_REVIEW_REQUIRED",
            answerability_accuracy: 1.0,
          },
          retrieved: [],
        },
      ],
    };
    const fetchMock = vi.fn((input: RequestInfo | URL) => {
      const url = String(input);
      if (url.includes("/auth/me")) return Promise.resolve(meResponse());
      if (url.includes("/failures")) return Promise.resolve(json({ failures: [] }));
      if (url.includes("/api/v1/eval/runs/r1")) return Promise.resolve(json(run));
      return Promise.resolve(json({ detail: "not mocked: " + url }, 500));
    });
    vi.stubGlobal("fetch", fetchMock);
    const user = userEvent.setup();

    render(
      <MemoryRouter initialEntries={["/evaluation/runs/r1"]}>
        {authShell(
          <Routes>
            <Route path="/evaluation/runs/:runId" element={<RunDetailPage />} />
          </Routes>,
        )}
      </MemoryRouter>,
    );

    expect(await screen.findByText("Objetivo · ATPCO")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: /Ver evidencia de/ }));
    expect(await screen.findByText("Pidió revisión humana")).toBeInTheDocument();
  });
});
