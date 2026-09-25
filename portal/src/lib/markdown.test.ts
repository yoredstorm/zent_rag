import { describe, expect, it } from "vitest";
import { renderMarkdownHtml } from "./markdown";

describe("renderMarkdownHtml", () => {
  it("convierte negritas en <strong>", () => {
    const { __html } = renderMarkdownHtml("La **Categoría 31** aplica.");
    expect(__html).toContain("<strong>Categoría 31</strong>");
  });

  it("renderiza encabezados, listas y tablas", () => {
    const { __html } = renderMarkdownHtml(
      ["### Valores", "", "- **1:** uno", "- **2:** dos", "", "| a | b |", "| --- | --- |", "| 1 | 2 |"].join("\n"),
    );
    expect(__html).toContain("<h3");
    expect(__html).toContain("<ul>");
    expect(__html).toContain("<table>");
  });

  it("un asterisco escapado queda literal (por eso el backend los normaliza)", () => {
    const { __html } = renderMarkdownHtml("\\*\\*Categoría 31\\*\\*");
    expect(__html).not.toContain("<strong>");
    expect(__html).toContain("**Categoría 31**");
  });

  it("sanitiza el HTML del modelo (anti prompt-injection)", () => {
    const { __html } = renderMarkdownHtml('<img src=x onerror="alert(1)">hola');
    expect(__html).not.toContain("onerror");
  });
});
