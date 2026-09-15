import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";
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

function json(body: unknown) {
  return new Response(JSON.stringify(body), { status: 200, headers: { "Content-Type": "application/json" } });
}

function stubApi() {
  const fetchMock = vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input);
    const method = (init?.method || "GET").toUpperCase();
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
    <MemoryRouter initialEntries={[path]}>
      <Routes>
        <Route path="/knowledge/sources/:sourceId" element={<SourceDetailPage />} />
      </Routes>
    </MemoryRouter>,
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
