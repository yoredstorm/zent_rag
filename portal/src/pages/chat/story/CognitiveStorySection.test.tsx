import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import { CognitiveStorySection } from "./CognitiveStorySection";

describe("CognitiveStorySection", () => {
  it("renderiza los pasos cognitivos", () => {
    render(
      <CognitiveStorySection
        raw={{
          cognitive_story: {
            schema_version: 1,
            normal: [
              {
                kind: "cognitive_plan",
                phase: "planning",
                status: "ok",
                metrics: { complexity: "L3", needs: 2 },
              },
              {
                kind: "cognitive_verification",
                phase: "verification",
                status: "warn",
                metrics: { action: "answer_with_limits", unsupported: 1 },
              },
            ],
            expanded: {},
            raw: {},
          },
        }}
      />,
    );
    expect(screen.getByText("Planeó la consulta")).toBeInTheDocument();
    expect(screen.getByText("Verificó la respuesta")).toBeInTheDocument();
  });

  it("no renderiza nada sin cognitive_story", () => {
    const { container } = render(<CognitiveStorySection raw={{}} />);
    expect(container.firstChild).toBeNull();
  });
});
