import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { ResizeHandle } from "./ResizeHandle";

function setup(axis: "x" | "y" = "x", value = 400) {
  const onChange = vi.fn();
  render(<ResizeHandle axis={axis} value={value} min={320} max={640} resetTo={400} onChange={onChange} label="Ancho" testId="h" />);
  return { onChange, handle: screen.getByRole("separator", { name: "Ancho" }) };
}

describe("ResizeHandle", () => {
  it("expone el valor y la orientación para lectores de pantalla", () => {
    const { handle } = setup("x");
    expect(handle).toHaveAttribute("aria-orientation", "vertical");
    expect(handle).toHaveAttribute("aria-valuenow", "400");
    expect(handle).toHaveAttribute("aria-valuemin", "320");
    expect(handle).toHaveAttribute("aria-valuemax", "640");
  });

  it("arrastrar hacia el lienzo agranda el panel y respeta los límites", () => {
    const { handle, onChange } = setup("x");
    fireEvent.pointerDown(handle, { button: 0, pointerId: 1, clientX: 1000 });
    fireEvent.pointerMove(handle, { pointerId: 1, clientX: 950 });
    expect(onChange).toHaveBeenLastCalledWith(450);
    fireEvent.pointerMove(handle, { pointerId: 1, clientX: 200 });
    expect(onChange).toHaveBeenLastCalledWith(640);
    fireEvent.pointerUp(handle, { pointerId: 1 });
    onChange.mockClear();
    fireEvent.pointerMove(handle, { pointerId: 1, clientX: 100 });
    expect(onChange).not.toHaveBeenCalled();
  });

  it("teclado: flechas, Inicio/Fin y doble clic restablece", () => {
    const { handle, onChange } = setup("y", 400);
    fireEvent.keyDown(handle, { key: "ArrowUp" });
    expect(onChange).toHaveBeenLastCalledWith(416);
    fireEvent.keyDown(handle, { key: "ArrowDown" });
    expect(onChange).toHaveBeenLastCalledWith(384);
    fireEvent.keyDown(handle, { key: "Home" });
    expect(onChange).toHaveBeenLastCalledWith(320);
    fireEvent.keyDown(handle, { key: "End" });
    expect(onChange).toHaveBeenLastCalledWith(640);
    fireEvent.doubleClick(handle);
    expect(onChange).toHaveBeenLastCalledWith(400);
  });
});
