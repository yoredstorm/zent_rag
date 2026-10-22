import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { EMPTY_MISSION, MissionCard } from "./MissionCard";

describe("MissionCard", () => {
  it("edita la misión en campos y no muestra JSON", () => {
    const onChange = vi.fn();
    render(<MissionCard value={{ ...EMPTY_MISSION, role: "Mentor" }} onChange={onChange} />);
    expect(screen.getByTestId("wf-mission-role")).toHaveValue("Mentor");
    fireEvent.change(screen.getByTestId("wf-mission-goal"), { target: { value: "El siguiente ejercicio" } });
    expect(onChange).toHaveBeenCalledWith(expect.objectContaining({ goal: "El siguiente ejercicio", role: "Mentor" }));
    expect(screen.queryByText(/\{/)).toBeNull();
  });
});
