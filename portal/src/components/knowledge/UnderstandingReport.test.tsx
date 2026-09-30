import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { UnderstandingReport } from "./UnderstandingReport";

describe("UnderstandingReport", () => {
  it("muestra conteos y el árbol sin interpretar HTML", () => {
    render(
      <UnderstandingReport
        data={{
          pipeline_state: "READY",
          report: {
            document: "Record layout",
            pages: 2,
            sections: 1,
            tables: 1,
            figures: 0,
            definitions: 1,
            technical_fields: 1,
            exact_literals: 2,
            extraction_quality: 0.96,
            pipeline_state: "READY",
            warnings: [],
          },
          tree: {
            title: "Record layout",
            children: [
              {
                type: "section",
                heading: "FCLAS",
                children: [{ type: "definition", text: "Fare Class" }],
              },
            ],
          },
        }}
      />,
    );
    const report = screen.getByTestId("understanding-report");
    expect(report).toHaveTextContent("Record layout");
    expect(report).toHaveTextContent("READY");
    expect(report).toHaveTextContent("Páginas 2");
    expect(report).toHaveTextContent("Campos 1");
    expect(report).toHaveTextContent("Calidad 96%");
    expect(report).toHaveTextContent("FCLAS");
    expect(report).toHaveTextContent("Fare Class");
  });
});
