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
  it("muestra cuatro experiencias y Avanzado cuando el flag está activo", async () => {
    const user = userEvent.setup();
    render(
      <MemoryRouter initialEntries={["/knowledge/improve"]}>
        <KnowledgeLayout simpleNavigation>
          <h1>contenido</h1>
        </KnowledgeLayout>
      </MemoryRouter>,
    );
    const nav = screen.getByRole("navigation", { name: "Secciones de conocimiento" });
    const links = within(nav).getAllByRole("link");
    expect(links.map((el) => el.textContent)).toEqual([
      "Resumen",
      "Fuentes",
      "Preguntar",
      "Mejorar",
    ]);
    expect(within(nav).getByRole("link", { name: "Mejorar" })).toHaveAttribute(
      "aria-current",
      "page",
    );
    await user.click(within(nav).getByRole("button", { name: "Herramientas avanzadas" }));
    expect(within(nav).getByRole("link", { name: "Mapa" })).toHaveAttribute(
      "href",
      "/knowledge/map",
    );
    expect(within(nav).getByRole("link", { name: "Fuentes SQL" })).toHaveAttribute(
      "href",
      "/knowledge/sql",
    );
  });

  it("muestra 5 pilares + Avanzado sin abrir el disclosure", () => {
    renderAt("/knowledge");
    const nav = screen.getByRole("navigation", { name: "Secciones de conocimiento" });
    const links = within(nav).getAllByRole("link");
    const buttons = within(nav).getAllByRole("button");
    expect(links.length + buttons.length).toBeLessThanOrEqual(6);
    expect(links.map((el) => el.textContent)).toEqual([
      "Inicio",
      "Explorador",
      "Salud",
      "Fuentes",
      "Actividad",
    ]);
    expect(within(nav).getByRole("button", { name: "Herramientas avanzadas" })).toHaveAttribute(
      "aria-expanded",
      "false"
    );
    expect(within(nav).queryByRole("link", { name: "Aprendizaje" })).not.toBeInTheDocument();
    expect(within(nav).queryByRole("link", { name: "Modelo" })).not.toBeInTheDocument();
  });

  it("marca el pilar activo por ruta", () => {
    renderAt("/knowledge/health");
    const nav = screen.getByRole("navigation", { name: "Secciones de conocimiento" });
    expect(within(nav).getByRole("link", { name: "Salud" })).toHaveAttribute(
      "aria-current",
      "page"
    );
    expect(within(nav).getByRole("link", { name: "Fuentes" })).not.toHaveAttribute(
      "aria-current"
    );
  });

  it("expone Avanzado al desplegar con las herramientas reales", async () => {
    const user = userEvent.setup();
    renderAt("/knowledge");
    const nav = screen.getByRole("navigation", { name: "Secciones de conocimiento" });
    await user.click(within(nav).getByRole("button", { name: "Herramientas avanzadas" }));
    expect(within(nav).getByRole("link", { name: "Estudio semántico" })).toHaveAttribute(
      "href",
      "/knowledge/understanding"
    );
    expect(within(nav).getByRole("link", { name: "Playground" })).toHaveAttribute(
      "href",
      "/knowledge/playground"
    );
    expect(within(nav).getByRole("link", { name: "Trabajos" })).toHaveAttribute(
      "href",
      "/knowledge/jobs"
    );
    expect(within(nav).getByRole("link", { name: "Conectores" })).toHaveAttribute(
      "href",
      "/connectors"
    );
  });

  it("mantiene Avanzado oculto hasta que se solicite, también en rutas avanzadas", async () => {
    const user = userEvent.setup();
    renderAt("/knowledge/understanding");
    const nav = screen.getByRole("navigation", { name: "Secciones de conocimiento" });
    expect(within(nav).getByRole("button", { name: "Herramientas avanzadas" })).toHaveAttribute(
      "aria-expanded",
      "false"
    );
    await user.click(within(nav).getByRole("button", { name: "Herramientas avanzadas" }));
    expect(within(nav).getByRole("link", { name: "Estudio semántico" })).toHaveAttribute(
      "aria-current",
      "page"
    );
  });
});
