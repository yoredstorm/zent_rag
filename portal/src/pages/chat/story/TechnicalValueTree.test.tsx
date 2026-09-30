import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import TechnicalValueTree from "./TechnicalValueTree";

describe("TechnicalValueTree", () => {
  it("presenta objetos como campos estructurados, no como bloque JSON", () => {
    render(<TechnicalValueTree value={{ model: "deepseek", nested: { score: 0.7 } }} />);

    expect(screen.getByText("model")).toBeTruthy();
    expect(screen.getByText("deepseek")).toBeTruthy();
    expect(screen.getByText("nested")).toBeTruthy();
    expect(document.querySelector("pre")).toBeNull();
  });
});
