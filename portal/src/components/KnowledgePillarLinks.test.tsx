import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it } from "vitest";
import { KnowledgePillarLinks } from "./KnowledgePillarLinks";

describe("KnowledgePillarLinks", () => {
  it("enlaza los 5 pilares del Knowledge OS", () => {
    render(
      <MemoryRouter>
        <KnowledgePillarLinks />
      </MemoryRouter>
    );
    const nav = screen.getByRole("navigation", { name: "Pilares de conocimiento" });
    expect(nav.querySelector('a[href="/knowledge"]')).toHaveTextContent("Inicio");
    expect(nav.querySelector('a[href="/knowledge/explorer"]')).toHaveTextContent(
      "Explorador"
    );
    expect(nav.querySelector('a[href="/knowledge/health"]')).toHaveTextContent("Salud");
    expect(nav.querySelector('a[href="/knowledge/sources"]')).toHaveTextContent("Fuentes");
    expect(nav.querySelector('a[href="/knowledge/activity"]')).toHaveTextContent(
      "Actividad"
    );
    expect(nav.querySelector('a[href="/knowledge/glossary"]')).toBeNull();
  });
});
