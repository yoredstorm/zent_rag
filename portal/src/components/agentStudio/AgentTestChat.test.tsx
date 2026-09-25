import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it } from "vitest";
import { AgentTestChat } from "./AgentTestChat";
import type { KnowledgeSource } from "./types";

const CAT31: KnowledgeSource = {
  id: "s1",
  name: "Cat31_dapp_C.pdf",
  type: "file",
  status: "indexed",
  document_count: 12,
  last_sync: null,
};

const REC2: KnowledgeSource = {
  ...CAT31,
  id: "s2",
  name: "Rec2_Cat10_dapp_C.pdf",
};

function renderChat(turns: Parameters<typeof AgentTestChat>[0]["turns"]) {
  return render(
    <MemoryRouter>
      <AgentTestChat
        turns={turns}
        input=""
        status=""
        playing={false}
        inactive={false}
        sources={[CAT31, REC2]}
        selectedIds={["s1", "s2"]}
        onInput={() => {}}
        onSubmit={(event) => event.preventDefault()}
      />
    </MemoryRouter>,
  );
}

describe("AgentTestChat · presentación de la respuesta", () => {
  it("renderiza markdown: la negrita se ve como negrita, no como asteriscos", () => {
    renderChat([
      {
        role: "assistant",
        text: "La **Categoría 31** define los cambios voluntarios.",
      },
    ]);

    const answer = screen.getByTestId("agent-answer");
    expect(answer.querySelector("strong")).not.toBeNull();
    expect(answer.querySelector("strong")?.textContent).toBe("Categoría 31");
    expect(answer.textContent).not.toContain("**");
  });

  it("renderiza encabezados, listas y tablas de la respuesta", () => {
    renderChat([
      {
        role: "assistant",
        text: [
          "El byte 105 define cómo aplicar el cargo.",
          "",
          "### Valores del Byte 105",
          "",
          "- **1:** el fee más alto entre los componentes cambiados",
          "- **2:** el fee más alto entre todos los componentes",
          "",
          "| Valor | Efecto |",
          "| --- | --- |",
          "| 1 | cambiados |",
        ].join("\n"),
      },
    ]);

    const answer = screen.getByTestId("agent-answer");
    expect(answer.querySelector("h3")?.textContent).toBe("Valores del Byte 105");
    expect(answer.querySelectorAll("li")).toHaveLength(2);
    expect(answer.querySelector("table")).not.toBeNull();
  });

  it("muestra cada fuente por separado, nunca los nombres pegados", () => {
    renderChat([
      {
        role: "assistant",
        text: "El byte 105 es Fee Application.",
        sources: ["s1", "s2"],
      },
    ]);

    expect(screen.getByText("Cat31_dapp_C.pdf")).toBeInTheDocument();
    expect(screen.getByText("Rec2_Cat10_dapp_C.pdf")).toBeInTheDocument();
    // Los nombres no se concatenan en un solo nodo.
    expect(screen.queryByText(/Cat31_dapp_C\.pdfRec2/)).toBeNull();
  });

  it("no interpreta como markdown el texto del usuario", () => {
    renderChat([{ role: "user", text: "cuéntame sobre categoría 31 y byte 105" }]);

    expect(screen.getByText("cuéntame sobre categoría 31 y byte 105")).toBeInTheDocument();
  });
});
