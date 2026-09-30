import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import ProbabilityDisplay from "./ProbabilityDisplay";

describe("ProbabilityDisplay", () => {
  it("muestra 0.7091 como 70.9%", () => {
    render(<ProbabilityDisplay value={0.7091} />);
    expect(screen.getByText("70.9%")).toBeTruthy();
  });

  it("no muestra porcentajes fuera de 0..1", () => {
    render(<ProbabilityDisplay value={709.1} fallback="No disponible" />);
    expect(screen.queryByText(/70910/)).toBeNull();
    expect(screen.getByText("No disponible")).toBeTruthy();
  });
});
