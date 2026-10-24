import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { ModeSwitch } from "./ModeSwitch";

describe("ModeSwitch", () => {
  it("ofrece Simple, Guiado y Avanzado y notifica el cambio", () => {
    const onChange = vi.fn();
    render(<ModeSwitch value="guided" onChange={onChange} />);
    expect(screen.getByTestId("solution-mode-simple")).toBeInTheDocument();
    expect(screen.getByTestId("solution-mode-guided")).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByTestId("solution-mode-advanced")).toBeInTheDocument();
    fireEvent.click(screen.getByTestId("solution-mode-advanced"));
    expect(onChange).toHaveBeenCalledWith("advanced");
  });
});
