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
    expect(links.map((el) => el.textContent)).toEqual(["Resumen", "Fuentes", "Aprendizaje"]);
    expect(within(nav).getByRole("button", { name: "Avanzado" })).toHaveAttribute(
      "aria-expanded",
      "false"
    );
    expect(within(nav).queryByRole("link", { name: "Semántica" })).not.toBeInTheDocument();
    expect(within(nav).queryByRole("link", { name: "Términos" })).not.toBeInTheDocument();
    expect(within(nav).queryByRole("link", { name: "Búsqueda" })).not.toBeInTheDocument();
  });

  it("no muestra sub-nav en Fuentes", () => {
    renderAt("/knowledge/sources");
    expect(screen.queryByRole("navigation", { name: /Subsecciones/ })).not.toBeInTheDocument();
    const primary = screen.getByRole("navigation", { name: "Secciones de conocimiento" });
    expect(within(primary).getByRole("link", { name: "Fuentes" })).toHaveAttribute(
      "aria-current",
      "page"
    );
  });

  it("muestra sub-nav de Aprendizaje con mapa", () => {
    renderAt("/knowledge/learning");
    const primary = screen.getByRole("navigation", { name: "Secciones de conocimiento" });
    expect(within(primary).getByRole("link", { name: "Aprendizaje" })).toHaveAttribute(
      "aria-current",
      "page"
    );
    const sub = screen.getByRole("navigation", { name: "Subsecciones de Aprendizaje" });
    expect(within(sub).getByRole("link", { name: "Aprendizaje" })).toHaveAttribute(
      "aria-current",
      "page"
    );
    expect(within(sub).getByRole("link", { name: "Mapa" })).toHaveAttribute("href", "/knowledge/map");
  });

  it("expone Avanzado al desplegar", async () => {
    const user = userEvent.setup();
    renderAt("/knowledge");
    const nav = screen.getByRole("navigation", { name: "Secciones de conocimiento" });
    await user.click(within(nav).getByRole("button", { name: "Avanzado" }));
    expect(within(nav).getByRole("link", { name: "Términos" })).toHaveAttribute(
      "href",
      "/knowledge/glossary"
    );
    expect(within(nav).getByRole("link", { name: "Catálogo" })).toHaveAttribute(
      "href",
      "/knowledge/catalog"
    );
    expect(within(nav).getByRole("link", { name: "Conectores" })).toHaveAttribute("href", "/connectors");
    expect(within(nav).getByRole("link", { name: "Trabajos" })).toHaveAttribute(
      "href",
      "/knowledge/jobs"
    );
    expect(within(nav).queryByRole("link", { name: "Workspaces" })).not.toBeInTheDocument();
    expect(within(nav).queryByRole("link", { name: "Knowledge Hub" })).not.toBeInTheDocument();
  });

  it("abre Avanzado automáticamente en Términos", () => {
    renderAt("/knowledge/glossary");
    const nav = screen.getByRole("navigation", { name: "Secciones de conocimiento" });
    expect(within(nav).getByRole("button", { name: "Avanzado" })).toHaveAttribute(
      "aria-expanded",
      "true"
    );
    expect(within(nav).getByRole("link", { name: "Términos" })).toHaveAttribute(
      "aria-current",
      "page"
    );
  });

  it("abre Avanzado automáticamente en jobs", () => {
    renderAt("/knowledge/jobs");
    const nav = screen.getByRole("navigation", { name: "Secciones de conocimiento" });
    expect(within(nav).getByRole("button", { name: "Avanzado" })).toHaveAttribute(
      "aria-expanded",
      "true"
    );
    expect(within(nav).getByRole("link", { name: "Trabajos" })).toHaveAttribute(
      "aria-current",
      "page"
    );
  });
});
