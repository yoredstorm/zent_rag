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
    expect(nav.querySelector('a[href="/knowledge"]')).toHaveTextContent("Resumen");
    expect(nav.querySelector('a[href="/knowledge/sources"]')).toHaveTextContent("Fuentes");
    expect(nav.querySelector('a[href="/knowledge/model"]')).toHaveTextContent("Modelo");
    expect(nav.querySelector('a[href="/knowledge/quality"]')).toHaveTextContent("Calidad");
    expect(nav.querySelector('a[href="/knowledge/evaluation"]')).toHaveTextContent(
      "Evaluación"
    );
    expect(nav.querySelector('a[href="/knowledge/glossary"]')).toBeNull();
  });
});
