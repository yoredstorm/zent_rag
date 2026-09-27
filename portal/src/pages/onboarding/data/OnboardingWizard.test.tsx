import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";
import { uploadFileWithProgress } from "../../../api";
import OnboardingWizardPage from "./OnboardingWizard";

const AUTH = vi.hoisted(() => ({
  session: { token: "rag_sess_t", organizationId: "org-1", roles: ["owner"], permissions: [] },
}));

vi.mock("../../../auth", () => ({ useAuth: () => AUTH }));

vi.mock("../../../api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../../../api")>();
  return { ...actual, uploadFileWithProgress: vi.fn() };
});

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
  const uploadMock = vi.mocked(uploadFileWithProgress);
  uploadMock.mockReset();
  uploadMock.mockImplementation(async (_path, form, options) => {
    const file = form.get("file") as File;
    uploads.push(file.name);
    options?.onProgress?.({ loaded: Math.round(file.size / 2), total: file.size });
    options?.onProgress?.({ loaded: file.size, total: file.size });
    return {
      ...SESSION,
      status: "CONNECTED",
      kb_source_id: `src-${file.name}`,
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
        filename: file.name,
        status: "created",
        source_id: `src-${file.name}`,
        name: file.name,
        job_id: `job-${file.name}`,
      },
    } as never;
  });

  const fetchMock = vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input);
    const method = (init?.method || "GET").toUpperCase();
    calls.push(`${method} ${url}`);
    if (url.endsWith("/data-onboarding/sessions") && method === "POST") {
      return Promise.resolve(json(SESSION, 201));
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
              { filename: "contrato-a.txt", job_id: "job-contrato-a.txt", job_status: "completed", job_progress: 100 },
              { filename: "contrato-b.txt", job_id: "job-contrato-b.txt", job_status: "completed", job_progress: 100 },
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
  return { fetchMock, uploads, calls, uploadMock };
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
  it("sube todos los archivos elegidos, muestra progreso y analiza el lote", async () => {
    const { uploads, calls, uploadMock } = stubApi();
    const user = userEvent.setup();
    renderWizard();

    await user.click(screen.getByTestId("source-kind-documents"));
    await waitFor(() => expect(screen.getByTestId("onboarding-file")).toBeInTheDocument());

    await user.upload(screen.getByTestId("onboarding-file"), [
      new File(["a".repeat(100)], "contrato-a.txt", { type: "text/plain" }),
      new File(["b".repeat(100)], "contrato-b.txt", { type: "text/plain" }),
    ]);
    expect(screen.getByText("contrato-a.txt")).toBeInTheDocument();
    expect(screen.getByTestId("upload-progress")).toHaveTextContent(
      "Listo para subir: 2 archivos",
    );
    await user.click(screen.getByRole("button", { name: "Subir 2 archivos" }));

    await waitFor(() => expect(uploads).toEqual(["contrato-a.txt", "contrato-b.txt"]));
    // Subida con callback de progreso real (bytes) por archivo.
    expect(uploadMock.mock.calls[0]?.[2]?.onProgress).toBeTypeOf("function");
    expect(calls.some((call) => call.includes("/analyze"))).toBe(true);

    await waitFor(() =>
      expect(screen.getByTestId("analyze-files")).toHaveTextContent("contrato-b.txt"),
    );
    // El poll de indexado marca los dos archivos como indexados.
    await waitFor(
      () => expect(screen.getByTestId("analyze-files")).toHaveTextContent("Indexado"),
      { timeout: 8000 },
    );
    expect(screen.getAllByRole("progressbar").length).toBeGreaterThan(0);
    expect(screen.getByRole("heading", { name: "Analizar" })).toBeInTheDocument();
  });
});
