import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";
import { ToastProvider } from "../../Toast";
import { parseSourceTab } from "./knowledgeCopy";
import SourceDetailPage from "./SourceDetail";

const AUTH = vi.hoisted(() => ({
  session: { token: "rag_sess_t", organizationId: "org-1", roles: ["owner"], permissions: [] },
}));

vi.mock("../../auth", () => ({ useAuth: () => AUTH }));

const LAST_SYNC = "2026-09-14T17:10:46.965517+00:00";

const SOURCE = {
  id: "src-1",
  name: "PIMENTEL ARENAS PABLO J.pdf",
  type: "file",
  status: "indexed",
  last_sync: LAST_SYNC,
  last_error: null,
  document_count: 5,
  error_count: 0,
  knowledge_base_id: "kb-1",
};

const KBS = {
  knowledge_bases: [
    { id: "kb-1", name: "Principal" },
    { id: "kb-2", name: "Ops" },
  ],
};

const DOCUMENTS = {
  documents: [
    {
      id: 1,
      external_id: "PIMENTEL ARENAS PABLO J.pdf",
      document_id: "doc-1",
      status: "active",
      last_seen_at: LAST_SYNC,
    },
  ],
};

const TABULAR = {
  source_id: "src-1",
  workbooks: [
    {
      id: "wb-1",
      filename: "ATPCO_TEST.xlsx",
      sheet_count: 1,
      table_count: 1,
      row_count: 6750,
      quality_score: 0.9,
      representations: { structured: true, semantic: true, lexical: true },
      chunk_count: 558,
      pipeline_version: "1.3",
    },
  ],
  map: "EXCEL MAP: 1 workbook(s), 1 table(s)\nWorkbook: ATPCO_TEST.xlsx",
  tables: [
    {
      id: "tbl-1",
      name: "ATPCO RECORD 2 RULES",
      sheet: "Record2",
      row_count: 6750,
      column_count: 24,
      header_rows: [1],
      detection_method: "heuristic",
    },
  ],
};

const TEST_QUERY_RESULT = {
  matched: true,
  source_id: "src-1",
  strategy: "tabular_lookup:row_label+column",
  confidence: 0.95,
  columns: ["Field Name", "Start Loc"],
  rows: [["Carrier Code", "6"]],
  row_count: 1,
  total: null,
  tables: ["ATPCO RECORD 2 RULES"],
  provenance: [
    {
      workbook: "ATPCO_TEST.xlsx",
      sheet: "Record2",
      table: "ATPCO RECORD 2 RULES",
      row: 5775,
      cell: "B5775",
      column: "Start Loc",
    },
  ],
  sql: "-- zent tabular",
};

function json(body: unknown) {
  return new Response(JSON.stringify(body), { status: 200, headers: { "Content-Type": "application/json" } });
}

function stubApi() {
  const fetchMock = vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input);
    const method = (init?.method || "GET").toUpperCase();
    if (url.includes("/tabular")) return Promise.resolve(json(TABULAR));
    if (url.includes("/table-preview"))
      return Promise.resolve(
        json({
          origin: "managed_db",
          table: "zent_atpco_attributes",
          columns: ["field_name", "start_loc"],
          rows: [["Carrier Code", 17]],
          count: 1,
        }),
      );
    if (url.includes("/test-query") && method === "POST")
      return Promise.resolve(json(TEST_QUERY_RESULT));
    if (url.includes("/documents")) return Promise.resolve(json(DOCUMENTS));
    if (url.includes("/knowledge-bases")) return Promise.resolve(json(KBS));
    if (url.includes("/api/v1/sources/src-1") && method === "PUT") {
      return Promise.resolve(json({ ...SOURCE, knowledge_base_id: "kb-2" }));
    }
    if (url.includes("/api/v1/sources/src-1") && method === "DELETE") {
      return Promise.resolve(json({ status: "deleted" }));
    }
    if (url.includes("/api/v1/sources/src-1")) return Promise.resolve(json(SOURCE));
    return Promise.resolve(json({}));
  });
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

afterEach(() => {
  vi.unstubAllGlobals();
});

function renderDetail(path = "/knowledge/sources/src-1") {
  return render(
    <ToastProvider>
      <MemoryRouter initialEntries={[path]}>
        <Routes>
          <Route path="/knowledge/sources/:sourceId" element={<SourceDetailPage />} />
        </Routes>
      </MemoryRouter>
    </ToastProvider>,
  );
}

describe("parseSourceTab", () => {
  it("mapea aliases viejos a resumen", () => {
    expect(parseSourceTab(null)).toBe("resumen");
    expect(parseSourceTab("overview")).toBe("resumen");
    expect(parseSourceTab("understood")).toBe("resumen");
    expect(parseSourceTab("content")).toBe("resumen");
    expect(parseSourceTab("permissions")).toBe("resumen");
    expect(parseSourceTab("advanced")).toBe("resumen");
    expect(parseSourceTab("sync")).toBe("sincronizar");
    expect(parseSourceTab("documentos")).toBe("documentos");
  });
});

describe("SourceDetailPage", () => {
  it("muestra 3 pestañas en español y no el ISO crudo", async () => {
    stubApi();
    renderDetail();
    await waitFor(() => expect(screen.getByTestId("source-resumen")).toBeInTheDocument());
    expect(screen.getByRole("tab", { name: "Resumen" })).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: "Documentos" })).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: "Sincronizar" })).toBeInTheDocument();
    expect(screen.queryByText("What Zent Understood")).toBeNull();
    expect(screen.queryByText("All sources")).toBeNull();
    expect(screen.getByText("Todas las fuentes")).toBeInTheDocument();
    expect(screen.getByText("Indexada")).toBeInTheDocument();
    expect(screen.queryByText(LAST_SYNC)).toBeNull();
    expect(screen.getByTestId("source-index-copy")).toHaveTextContent(/el agente puede citar/);
  });

  it("muestra la estructura tabular del archivo cuando existe", async () => {
    stubApi();
    renderDetail();
    await waitFor(() => expect(screen.getByTestId("source-resumen")).toBeInTheDocument());
    expect(await screen.findByTestId("source-tabular")).toBeInTheDocument();
    expect(screen.getByTestId("source-tabular")).toHaveTextContent("ATPCO_TEST.xlsx");
    expect(screen.getByTestId("source-tabular")).toHaveTextContent("ATPCO RECORD 2 RULES");
    expect(screen.getByTestId("source-tabular")).toHaveTextContent("6,750 filas");
    expect(screen.getByTestId("source-tabular")).toHaveTextContent("558 fragmentos");
    expect(screen.getByTestId("source-tabular")).toHaveTextContent("pipeline 1.3");
  });

  it("prueba una consulta exacta contra la fuente y muestra procedencia", async () => {
    const fetchMock = stubApi();
    const user = userEvent.setup();
    renderDetail();
    await waitFor(() => expect(screen.getByTestId("source-resumen")).toBeInTheDocument());
    const input = await screen.findByTestId("source-test-query");
    await user.type(input, "posición de Carrier Code");
    await user.click(screen.getByTestId("source-test-run"));
    await waitFor(() => {
      expect(screen.getByTestId("source-test-result")).toHaveTextContent("Carrier Code");
    });
    expect(screen.getByTestId("source-test-result")).toHaveTextContent("6");
    expect(screen.getByTestId("source-test-result")).toHaveTextContent("B5775");
    expect(
      fetchMock.mock.calls.some(
        ([url, init]) =>
          String(url).includes("/test-query") && (init as RequestInit)?.method === "POST",
      ),
    ).toBe(true);
  });

  it("muestra la vista previa de la tabla materializada y ofrece SQL", async () => {
    stubApi();
    const user = userEvent.setup();
    renderDetail();
    await waitFor(() => expect(screen.getByTestId("source-resumen")).toBeInTheDocument());

    await user.click(await screen.findByTestId("source-preview-run"));
    await waitFor(() => {
      expect(screen.getByTestId("source-preview")).toHaveTextContent("zent_atpco_attributes");
    });
    expect(screen.getByTestId("source-preview")).toHaveTextContent("Carrier Code");
    expect(screen.getByTestId("source-preview")).toHaveTextContent("Managed DB");

    await user.click(screen.getByTestId("source-sql-open"));
    expect(
      await screen.findByRole("dialog", { name: "Consultar la tabla materializada" }),
    ).toBeInTheDocument();
  });

  it("lista el documento indexado", async () => {
    stubApi();
    const user = userEvent.setup();
    renderDetail();
    await waitFor(() => expect(screen.getByTestId("source-resumen")).toBeInTheDocument());
    await user.click(screen.getByRole("tab", { name: "Documentos" }));
    expect(await screen.findByTestId("source-documentos")).toBeInTheDocument();
    expect(screen.getByTestId("source-documentos")).toHaveTextContent("PIMENTEL ARENAS PABLO J.pdf");
    expect(screen.queryByText(LAST_SYNC)).toBeNull();
  });

  it("cambia la colección con PUT", async () => {
    const fetchMock = stubApi();
    const user = userEvent.setup();
    renderDetail();
    const select = await screen.findByTestId("source-kb");
    await user.selectOptions(select, "kb-2");
    await waitFor(() => {
      expect(
        fetchMock.mock.calls.some(
          ([url, init]) => String(url).includes("/api/v1/sources/src-1") && (init as RequestInit)?.method === "PUT",
        ),
      ).toBe(true);
    });
  });

  it("elimina la fuente y vuelve a la lista", async () => {
    const fetchMock = stubApi();
    const user = userEvent.setup();
    renderDetail();
    await waitFor(() => expect(screen.getByTestId("source-delete")).toBeInTheDocument());
    await user.click(screen.getByTestId("source-delete"));
    await user.click(within(screen.getByRole("alertdialog")).getByRole("button", { name: "Eliminar" }));
    await waitFor(() => {
      expect(
        fetchMock.mock.calls.some(
          ([url, init]) => String(url).includes("/api/v1/sources/src-1") && (init as RequestInit)?.method === "DELETE",
        ),
      ).toBe(true);
    });
  });
});
