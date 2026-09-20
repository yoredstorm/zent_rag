import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";
import { COPY } from "./knowledgeCopy";
import KnowledgeSourcesPage from "./Sources";

const AUTH = vi.hoisted(() => ({
  session: { token: "rag_sess_t", organizationId: "org-1", roles: ["owner"], permissions: [] },
}));

vi.mock("../../auth", () => ({ useAuth: () => AUTH }));

const FILE_SOURCE = {
  id: "src-1",
  name: "PIMENTEL ARENAS PABLO J.pdf",
  type: "file",
  status: "indexed",
  last_sync: "2026-09-14T17:10:46.965517+00:00",
  last_error: null,
  document_count: 5,
  error_count: 0,
  knowledge_base_id: "kb-1",
};

const SQL_SOURCE = {
  id: "src-sql",
  name: "Inventario",
  type: "sql",
  status: "ready",
  last_sync: "2026-09-14T17:10:46.965517+00:00",
  last_error: null,
  document_count: 2,
  error_count: 0,
  knowledge_base_id: "kb-1",
};

const KBS = [
  { id: "kb-1", name: "Principal" },
  { id: "kb-2", name: "Ops" },
];

function json(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
}

function stubApi(sources: unknown[], kbs = KBS) {
  const fetchMock = vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input);
    const method = (init?.method || "GET").toUpperCase();
    if (url.includes("/files/upload-batch") && method === "POST") {
      const form = init?.body as FormData;
      const file = form?.getAll("files")[0] as File | undefined;
      const filename = file?.name || "cv.pdf";
      return Promise.resolve(
        json({
          items: [
            {
              filename,
              status: "created",
              source_id: `src-${filename}`,
              name: filename,
              job_id: "job-1",
            },
          ],
          created: 1,
          duplicates: 0,
          rejected: 0,
          failed: 0,
        }),
      );
    }
    if (url.includes("/knowledge-bases") && method === "POST") {
      return Promise.resolve(json({ id: "kb-1", name: "Principal" }, 201));
    }
    if (url.includes("/knowledge-bases")) return Promise.resolve(json({ knowledge_bases: kbs }));
    if (url.includes("/api/v1/sources/") && method === "PUT") {
      return Promise.resolve(json({ ...FILE_SOURCE, knowledge_base_id: "kb-2" }));
    }
    if (url.includes("/api/v1/sources/") && method === "DELETE") {
      return Promise.resolve(json({ status: "deleted" }));
    }
    if (url.includes("/api/v1/sources")) return Promise.resolve(json({ sources }));
    return Promise.resolve(json({}));
  });
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

afterEach(() => {
  vi.unstubAllGlobals();
});

function renderSources() {
  return render(
    <MemoryRouter initialEntries={["/knowledge/sources"]}>
      <KnowledgeSourcesPage />
    </MemoryRouter>,
  );
}

describe("KnowledgeSourcesPage", () => {
  it("pinta español, un hint y no Perfilizar en un PDF", async () => {
    stubApi([FILE_SOURCE]);
    renderSources();
    await waitFor(() => expect(screen.getByTestId("source-card-src-1")).toBeInTheDocument());
    expect(screen.getAllByText(/Los agentes eligen estas fuentes/)).toHaveLength(1);
    expect(screen.getByRole("link", { name: COPY.open })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: `Sincronizar ${FILE_SOURCE.name}` })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: `Eliminar ${FILE_SOURCE.name}` })).toBeInTheDocument();
    expect(screen.getByText(/Documentos:/)).toBeInTheDocument();
    expect(screen.getByText("Indexada")).toBeInTheDocument();
    expect(screen.queryByText("Open")).toBeNull();
    expect(screen.queryByRole("button", { name: `Perfilizar ${FILE_SOURCE.name}` })).toBeNull();
  });

  it("muestra Perfilizar solo en SQL", async () => {
    stubApi([SQL_SOURCE]);
    renderSources();
    await waitFor(() => expect(screen.getByTestId("source-card-src-sql")).toBeInTheDocument());
    expect(screen.getByRole("button", { name: "Perfilizar Inventario" })).toBeInTheDocument();
  });

  it("sube archivos sin pedir nombre y muestra el resultado", async () => {
    const fetchMock = stubApi([]);
    const user = userEvent.setup();
    renderSources();
    await waitFor(() => expect(screen.getAllByRole("button", { name: /Nueva fuente/ }).length).toBeGreaterThan(0));
    await user.click(screen.getAllByRole("button", { name: /Nueva fuente/ })[0]);
    const input = await screen.findByTestId("source-files");
    const pdf = new File(["%PDF"], "cv.pdf", { type: "application/pdf" });
    await user.upload(input, pdf);
    await user.click(screen.getByRole("button", { name: "Subir e indexar" }));
    await waitFor(() => {
      expect(fetchMock.mock.calls.some(([url, init]) => String(url).includes("/files/upload-batch") && (init as RequestInit)?.method === "POST")).toBe(true);
    });
    expect(await screen.findByText("En cola de indexado")).toBeInTheDocument();
    expect(screen.queryByLabelText("Nombre")).toBeNull();
  });

  it("sube N archivos en pedidos separados (uno por archivo)", async () => {
    const fetchMock = stubApi([]);
    const user = userEvent.setup();
    renderSources();
    await waitFor(() => expect(screen.getAllByRole("button", { name: /Nueva fuente/ }).length).toBeGreaterThan(0));
    await user.click(screen.getAllByRole("button", { name: /Nueva fuente/ })[0]);
    const input = await screen.findByTestId("source-files");
    await user.upload(input, [
      new File(["%PDF"], "uno.pdf", { type: "application/pdf" }),
      new File(["%PDF"], "dos.pdf", { type: "application/pdf" }),
    ]);
    await user.click(screen.getByRole("button", { name: "Subir 2 archivos" }));
    await waitFor(() => {
      const uploads = fetchMock.mock.calls.filter(
        ([url, init]) => String(url).includes("/files/upload-batch") && (init as RequestInit)?.method === "POST",
      );
      // Un request por archivo: así ningún lote supera el límite del body.
      expect(uploads).toHaveLength(2);
      for (const [, init] of uploads) {
        const body = (init as RequestInit)?.body as FormData;
        expect(body.getAll("files")).toHaveLength(1);
      }
      expect(
        uploads.map(([, init]) =>
          (((init as RequestInit)?.body as FormData).getAll("files")[0] as File).name,
        ),
      ).toEqual(["uno.pdf", "dos.pdf"]);
    });
    const results = within(await screen.findByTestId("upload-results"));
    expect(await results.findByText("uno.pdf")).toBeInTheDocument();
    expect(results.getByText("dos.pdf")).toBeInTheDocument();
  });

  it("si un archivo falla con 413 sigue con el siguiente", async () => {
    const uploaded: string[] = [];
    const fetchMock = vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      const method = (init?.method || "GET").toUpperCase();
      if (url.includes("/files/upload-batch") && method === "POST") {
        const form = init?.body as FormData;
        const file = form.getAll("files")[0] as File;
        uploaded.push(file.name);
        if (file.name === "grande.pdf") {
          return Promise.resolve(
            new Response("<html>413 Request Entity Too Large</html>", {
              status: 413,
              headers: { "Content-Type": "text/html" },
            }),
          );
        }
        return Promise.resolve(
          json({
            items: [
              {
                filename: file.name,
                status: "created",
                source_id: "src-chico",
                name: file.name,
                job_id: "job-1",
              },
            ],
            created: 1,
            duplicates: 0,
            rejected: 0,
            failed: 0,
          }),
        );
      }
      if (url.includes("/knowledge-bases")) return Promise.resolve(json({ knowledge_bases: KBS }));
      if (url.includes("/api/v1/sources")) return Promise.resolve(json({ sources: [] }));
      return Promise.resolve(json({}));
    });
    vi.stubGlobal("fetch", fetchMock);
    const user = userEvent.setup();
    renderSources();
    await waitFor(() =>
      expect(screen.getAllByRole("button", { name: /Nueva fuente/ }).length).toBeGreaterThan(0),
    );
    await user.click(screen.getAllByRole("button", { name: /Nueva fuente/ })[0]);
    const input = await screen.findByTestId("source-files");
    await user.upload(input, [
      new File(["%PDF"], "grande.pdf", { type: "application/pdf" }),
      new File(["%PDF"], "chico.pdf", { type: "application/pdf" }),
    ]);
    await user.click(screen.getByRole("button", { name: "Subir 2 archivos" }));
    expect(
      await screen.findByText("Supera el máximo por archivo (25 MB). Probá con uno más chico."),
    ).toBeInTheDocument();
    expect(uploaded).toEqual(["grande.pdf", "chico.pdf"]);
    expect(await screen.findByText("1 archivo en cola de indexado.")).toBeInTheDocument();
  });

  it("avisa duplicado por archivo y permite subir igual", async () => {
    const fetchMock = vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      const method = (init?.method || "GET").toUpperCase();
      if (url.includes("/files/upload-batch") && method === "POST") {
        if (url.includes("force=true")) {
          return Promise.resolve(
            json({
              items: [
                {
                  filename: "cv.pdf",
                  status: "created",
                  source_id: "src-copy",
                  name: "cv.pdf (2)",
                  job_id: "job-2",
                },
              ],
              created: 1,
              duplicates: 0,
              rejected: 0,
              failed: 0,
            }),
          );
        }
        return Promise.resolve(
          json({
            items: [
              {
                filename: "cv.pdf",
                status: "duplicate",
                error: "Ya existe una fuente con el mismo nombre: cv.pdf",
                existing_source_id: "src-1",
                existing_name: "cv.pdf",
              },
            ],
            created: 0,
            duplicates: 1,
            rejected: 0,
            failed: 0,
          }),
        );
      }
      if (url.includes("/knowledge-bases") && method === "POST") {
        return Promise.resolve(json({ id: "kb-1", name: "Principal" }, 201));
      }
      if (url.includes("/knowledge-bases")) return Promise.resolve(json({ knowledge_bases: KBS }));
      if (url.includes("/api/v1/sources")) return Promise.resolve(json({ sources: [] }));
      return Promise.resolve(json({}));
    });
    vi.stubGlobal("fetch", fetchMock);
    const user = userEvent.setup();
    renderSources();
    await waitFor(() =>
      expect(screen.getAllByRole("button", { name: /Nueva fuente/ }).length).toBeGreaterThan(0),
    );
    await user.click(screen.getAllByRole("button", { name: /Nueva fuente/ })[0]);
    const input = await screen.findByTestId("source-files");
    const pdf = new File(["%PDF"], "cv.pdf", { type: "application/pdf" });
    await user.upload(input, pdf);
    await user.click(screen.getByRole("button", { name: "Subir e indexar" }));

    expect(await screen.findByText("Ya existe")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Abrir existente" })).toHaveAttribute(
      "href",
      "/knowledge/sources/src-1",
    );

    await user.click(screen.getByRole("button", { name: "Subir igual" }));
    await waitFor(() => {
      expect(
        fetchMock.mock.calls.some(
          ([url, init]) =>
            String(url).includes("force=true") && (init as RequestInit)?.method === "POST",
        ),
      ).toBe(true);
    });
    expect(await screen.findByText("En cola de indexado")).toBeInTheDocument();
  });

  it("elimina una fuente tras confirmar", async () => {
    const fetchMock = stubApi([FILE_SOURCE]);
    const user = userEvent.setup();
    renderSources();
    await waitFor(() => expect(screen.getByTestId("source-delete-src-1")).toBeInTheDocument());
    await user.click(screen.getByTestId("source-delete-src-1"));
    await user.click(within(screen.getByRole("alertdialog")).getByRole("button", { name: COPY.deleteSource }));
    await waitFor(() => {
      expect(
        fetchMock.mock.calls.some(
          ([url, init]) => String(url).includes("/api/v1/sources/src-1") && (init as RequestInit)?.method === "DELETE",
        ),
      ).toBe(true);
    });
  });
});
