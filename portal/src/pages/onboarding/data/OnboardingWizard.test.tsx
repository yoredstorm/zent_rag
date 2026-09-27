import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";
import OnboardingWizardPage from "./OnboardingWizard";

const AUTH = vi.hoisted(() => ({
  session: { token: "rag_sess_t", organizationId: "org-1", roles: ["owner"], permissions: [] },
}));

vi.mock("../../../auth", () => ({ useAuth: () => AUTH }));

const SESSION = {
  id: "sess-1",
  kind: "documents",
  status: "NOT_STARTED",
  step: "connect",
  connector_id: null,
  catalog_source_id: null,
  kb_source_id: null,
  skipped_review: false,
  skipped_test: false,
  usable: false,
  warning: null,
  state: {},
};

function json(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

function stubApi() {
  const uploads: string[] = [];
  const calls: string[] = [];
  const fetchMock = vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input);
    const method = (init?.method || "GET").toUpperCase();
    calls.push(`${method} ${url}`);
    if (url.endsWith("/data-onboarding/sessions") && method === "POST") {
      return Promise.resolve(json(SESSION, 201));
    }
    if (url.includes("/connect/upload") && method === "POST") {
      const form = init?.body as FormData;
      const file = form.get("file") as File | null;
      const filename = file?.name || "archivo";
      uploads.push(filename);
      return Promise.resolve(
        json({
          ...SESSION,
          status: "CONNECTED",
          kb_source_id: `src-${filename}`,
          state: {
            source_ids: uploads.map((name) => `src-${name}`),
            sources: uploads.map((name) => ({
              source_id: `src-${name}`,
              filename: name,
              status: "created",
              job_id: `job-${name}`,
            })),
            job_ids: uploads.map((name) => `job-${name}`),
          },
          upload: {
            filename,
            status: "created",
            source_id: `src-${filename}`,
            name: filename,
            job_id: `job-${filename}`,
          },
        }),
      );
    }
    if (url.includes("/analyze") && method === "POST") {
      return Promise.resolve(
        json({ ...SESSION, status: "ANALYZING", kb_source_id: "src-contrato-a.txt" }),
      );
    }
    if (url.includes("/progress")) {
      return Promise.resolve(
        json({
          session: {
            ...SESSION,
            status: "REVIEW_REQUIRED",
            step: "review",
            kb_source_id: "src-contrato-a.txt",
          },
          phases: [{ id: "content", label: "Texto extraído", state: "done" }],
          headline: "Zent ya entendió tus documentos",
          technical_details: {
            files: [
              { filename: "contrato-a.txt", job_id: "job-1", job_status: "completed", job_progress: 100 },
              { filename: "contrato-b.txt", job_id: "job-2", job_status: "running", job_progress: 10 },
            ],
          },
          percent: 100,
          glimpses: [],
        }),
      );
    }
    if (url.includes("/understanding")) {
      return Promise.resolve(json({ flow: "documents", suggestions: [] }));
    }
    if (url.includes("/data-onboarding/sessions/")) {
      return Promise.resolve(json(SESSION));
    }
    return Promise.resolve(json({}));
  });
  vi.stubGlobal("fetch", fetchMock);
  return { fetchMock, uploads, calls };
}

afterEach(() => {
  vi.unstubAllGlobals();
});

function renderWizard() {
  return render(
    <MemoryRouter initialEntries={["/knowledge/add"]}>
      <Routes>
        <Route path="/knowledge/add" element={<OnboardingWizardPage />} />
        <Route path="/knowledge/add/:sessionId" element={<OnboardingWizardPage />} />
      </Routes>
    </MemoryRouter>,
  );
}

describe("Asistente de conocimiento en lote", () => {
  it("sube todos los archivos elegidos y analiza el lote completo", async () => {
    const { uploads, calls } = stubApi();
    const user = userEvent.setup();
    renderWizard();

    await user.click(screen.getByTestId("source-kind-documents"));
    await waitFor(() => expect(screen.getByTestId("onboarding-file")).toBeInTheDocument());

    await user.upload(screen.getByTestId("onboarding-file"), [
      new File(["a"], "contrato-a.txt", { type: "text/plain" }),
      new File(["b"], "contrato-b.txt", { type: "text/plain" }),
    ]);
    expect(screen.getByText("contrato-a.txt")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Subir 2 archivos" }));

    await waitFor(() => expect(uploads).toEqual(["contrato-a.txt", "contrato-b.txt"]));
    await waitFor(() =>
      expect(calls.some((call) => call.includes("/analyze"))).toBe(true),
    );
    await waitFor(() =>
      expect(screen.getByTestId("analyze-files")).toHaveTextContent("contrato-b.txt"),
    );
    expect(screen.getByTestId("analyze-files")).toHaveTextContent("Listo");
    expect(screen.getByRole("heading", { name: "Analizar" })).toBeInTheDocument();
  });
});
