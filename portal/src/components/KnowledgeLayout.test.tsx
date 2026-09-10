import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it } from "vitest";
import { KnowledgeLayout } from "./KnowledgeLayout";

function renderAt(path: string) {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <KnowledgeLayout>
        <h1>contenido</h1>
      </KnowledgeLayout>
    </MemoryRouter>
  );
}

describe("KnowledgeLayout", () => {
  it("muestra ≤6 pestañas visibles sin abrir Avanzado", () => {
    renderAt("/knowledge");
    const nav = screen.getByRole("navigation", { name: "Secciones de conocimiento" });
    const links = within(nav).getAllByRole("link");
    const buttons = within(nav).getAllByRole("button");
    expect(links.length + buttons.length).toBeLessThanOrEqual(6);
    expect(links.map((el) => el.textContent)).toEqual([
      "Resumen",
      "Fuentes",
      "Semántica",
      "Mejora",
    ]);
    expect(within(nav).getByRole("button", { name: "Avanzado" })).toHaveAttribute(
      "aria-expanded",
      "false"
    );
    expect(within(nav).queryByRole("link", { name: "Búsqueda" })).not.toBeInTheDocument();
    expect(within(nav).queryByRole("link", { name: "Aprendizaje" })).not.toBeInTheDocument();
    expect(within(nav).queryByRole("link", { name: "Entendimiento" })).not.toBeInTheDocument();
  });

  it("marca el pilar Semántica y muestra sub-nav en glosario", () => {
    renderAt("/knowledge/glossary");
    const primary = screen.getByRole("navigation", { name: "Secciones de conocimiento" });
    expect(within(primary).getByRole("link", { name: "Semántica" })).toHaveAttribute(
      "aria-current",
      "page"
    );
    const sub = screen.getByRole("navigation", { name: "Subsecciones de Semántica" });
    expect(within(sub).getByRole("link", { name: "Términos" })).toHaveAttribute(
      "aria-current",
      "page"
    );
    expect(within(sub).getByRole("link", { name: "Entendimiento" })).toHaveAttribute(
      "href",
      "/knowledge/understanding"
    );
  });

  it("muestra sub-nav de Mejora en aprendizaje y mapa", () => {
    renderAt("/knowledge/learning");
    const sub = screen.getByRole("navigation", { name: "Subsecciones de Mejora" });
    expect(within(sub).getByRole("link", { name: "Aprendizaje" })).toHaveAttribute(
      "aria-current",
      "page"
    );
    expect(within(sub).getByRole("link", { name: "Mapa" })).toHaveAttribute("href", "/knowledge/map");
    expect(within(sub).getByRole("link", { name: "Revisión" })).toHaveAttribute(
      "href",
      "/knowledge/review"
    );
  });

  it("expone Avanzado al desplegar y en rutas avanzadas", async () => {
    const user = userEvent.setup();
    renderAt("/knowledge");
    const nav = screen.getByRole("navigation", { name: "Secciones de conocimiento" });
    await user.click(within(nav).getByRole("button", { name: "Avanzado" }));
    expect(within(nav).getByRole("link", { name: "Sincronización" })).toHaveAttribute(
      "href",
      "/knowledge/jobs"
    );
    expect(within(nav).getByRole("link", { name: "Knowledge Hub" })).toHaveAttribute(
      "href",
      "/knowledge-hub"
    );
  });

  it("abre Avanzado automáticamente en jobs", () => {
    renderAt("/knowledge/jobs");
    const nav = screen.getByRole("navigation", { name: "Secciones de conocimiento" });
    expect(within(nav).getByRole("button", { name: "Avanzado" })).toHaveAttribute(
      "aria-expanded",
      "true"
    );
    expect(within(nav).getByRole("link", { name: "Sincronización" })).toHaveAttribute(
      "aria-current",
      "page"
    );
  });
});
