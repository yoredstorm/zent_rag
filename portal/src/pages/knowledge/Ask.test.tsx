import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import KnowledgeAskPage from "./Ask";

const api = vi.hoisted(() => vi.fn());

vi.mock("../../api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../../api")>();
  return { ...actual, api };
});

const AUTH = vi.hoisted(() => ({
  session: {
    token: "t",
    organizationId: "o",
    permissions: ["knowledge:read", "knowledge:write"],
  },
}));

vi.mock("../../auth", () => ({ useAuth: () => AUTH }));

function json(body: unknown) {
  return Promise.resolve(body);
}

beforeEach(() => {
  api.mockReset();
  api.mockImplementation((url: string, init?: { method?: string }) => {
    if (url.endsWith("/knowledge/workspaces") && !init?.method) {
      return json({ corpora: [{ id: "c1", name: "Base de pruebas", source_count: 1 }] });
    }
    if (url.endsWith("/chat")) {
      return json({
        grounded: {
          answer: "La política exige aviso previo de treinta días [1].",
          citations: [
            {
              document_name: "politica.pdf",
              document_id: "d1",
              page: 7,
              section_path: ["Aprobaciones"],
              locator: "p. 7",
              excerpt: "La política exige aviso previo de treinta días.",
            },
          ],
          evidence_ids: ["e1"],
        },
      });
    }
    if (url.endsWith("/knowledge/evidence/e1")) {
      return json({
        id: "e1",
        source_id: "s1",
        document_id: "d1",
        page: 7,
        excerpt: "La política exige aviso previo de treinta días.",
      });
    }
    if (url.endsWith("/nutrition/feedback")) {
      return json({ status: "recorded" });
    }
    return json({});
  });
});

describe("KnowledgeAskPage", () => {
  it("responde con cita real y resuelve su evidencia", async () => {
    const user = userEvent.setup();
    render(
      <MemoryRouter initialEntries={["/knowledge/ask"]}>
        <KnowledgeAskPage />
      </MemoryRouter>,
    );

    await screen.findByRole("option", { name: "Base de pruebas" });
    await user.type(screen.getByLabelText("Pregunta"), "¿Cuál es el plazo?");
    await user.click(screen.getByRole("button", { name: "Preguntar" }));

    await waitFor(() => expect(screen.getByTestId("ask-citations")).toBeInTheDocument());
    expect(screen.getByTestId("ask-citations")).toHaveTextContent("página 7");
    await user.click(screen.getByRole("button", { name: "Ver dónde lo encontró" }));
    await waitFor(() =>
      expect(screen.getByRole("link", { name: "Abrir fuente" })).toBeInTheDocument(),
    );
    expect(screen.getByRole("link", { name: "Abrir fuente" })).toHaveAttribute(
      "href",
      "/knowledge/sources/s1",
    );

    await user.click(screen.getByRole("button", { name: "Sí" }));
    await waitFor(() =>
      expect(screen.getByText(/señal quedó registrada/)).toBeInTheDocument(),
    );
  });
});
