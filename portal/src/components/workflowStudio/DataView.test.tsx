import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import { DataView } from "./DataView";

describe("DataView", () => {
  it("muestra filas humanas y oculta el JSON por defecto", () => {
    render(
      <DataView
        data={{ fecha: "2026-09-13", tienda_id: 148, total: 18450.5, activo: true, nota: null }}
        testId="view"
      />,
    );
    expect(screen.getByText("Fecha")).toBeInTheDocument();
    expect(screen.getByText("13/09/2026")).toBeInTheDocument();
    expect(screen.getByText("148")).toBeInTheDocument();
    expect(screen.getByText("18,450.5")).toBeInTheDocument();
    expect(screen.getByText("Sí")).toBeInTheDocument();
    expect(screen.queryByTestId("view-json")).toBeNull();
  });

  it("resume arrays y muestra tabla de registros", async () => {
    const user = userEvent.setup();
    render(
      <DataView
        data={{
          ventas: [
            { vendedor: "Carlos", total: 1200 },
            { vendedor: "Ana", total: 900 },
          ],
        }}
        testId="view"
      />,
    );
    expect(screen.getByText("2 elementos")).toBeInTheDocument();
    await user.click(screen.getByTestId("data-registers-ventas"));
    const table = screen.getByTestId("data-table-ventas");
    expect(table).toHaveTextContent("Carlos");
    expect(table).toHaveTextContent("Ana");
  });

  it("permite ver el JSON al final", async () => {
    const user = userEvent.setup();
    render(<DataView data={{ estado: "ACTIVO" }} testId="view" />);
    await user.click(screen.getByTestId("view-json-toggle"));
    expect(screen.getByTestId("view-json")).toHaveTextContent('"estado": "ACTIVO"');
  });

  it("indica cuando no hay datos", () => {
    render(<DataView data={null} testId="view" emptyHint="Sin datos aún." />);
    expect(screen.getByTestId("view-empty")).toHaveTextContent("Sin datos aún.");
  });
});
