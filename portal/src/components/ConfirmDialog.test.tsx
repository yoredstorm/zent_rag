import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { ConfirmDialog } from "./ConfirmDialog";
import { expectAxeToHaveNoViolations } from "../test/axe";

describe("ConfirmDialog", () => {
  it("no renderiza nada cuando está cerrado", () => {
    render(
      <ConfirmDialog open={false} title="X" body="y" onConfirm={() => {}} onCancel={() => {}} />
    );
    expect(screen.queryByRole("alertdialog")).toBeNull();
  });

  it("muestra título, cuerpo y botones; confirmar dispara onConfirm", async () => {
    const user = userEvent.setup();
    const onConfirm = vi.fn();
    const onCancel = vi.fn();
    render(
      <ConfirmDialog
        open
        title="Suspend Acme"
        body={<p>Impacto: se bloquean requests.</p>}
        onConfirm={onConfirm}
        onCancel={onCancel}
      />
    );
    expect(screen.getByRole("alertdialog")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Confirmar" }));
    expect(onConfirm).toHaveBeenCalledTimes(1);
  });

  it("Escape cancela sin confirmar", async () => {
    const user = userEvent.setup();
    const onCancel = vi.fn();
    render(
      <ConfirmDialog open title="X" body="y" onConfirm={() => {}} onCancel={onCancel} />
    );
    await user.keyboard("{Escape}");
    expect(onCancel).toHaveBeenCalledTimes(1);
  });

  it("deshabilita confirmar mientras busy", async () => {
    render(
      <ConfirmDialog open title="X" body="y" busy onConfirm={() => {}} onCancel={() => {}} />
    );
    expect(screen.getByRole("button", { name: "Procesando…" })).toBeDisabled();
  });

  it("exige escribir la frase exacta (type-to-confirm) para operaciones graves", async () => {
    const user = userEvent.setup();
    const onConfirm = vi.fn();
    render(
      <ConfirmDialog
        open
        title="Suspend Acme"
        body={<p>Impacto severo.</p>}
        confirmText="SUSPEND"
        onConfirm={onConfirm}
        onCancel={() => {}}
      />
    );
    const confirmBtn = screen.getByRole("button", { name: "Confirmar" });
    expect(confirmBtn).toBeDisabled();

    const input = screen.getByRole("textbox");
    await user.type(input, "suspend");
    expect(confirmBtn).toBeDisabled();

    await user.clear(input);
    await user.type(input, "SUSPEND");
    expect(confirmBtn).toBeEnabled();
    await user.click(confirmBtn);
    expect(onConfirm).toHaveBeenCalledTimes(1);
  });

  it("sin violaciones de accesibilidad", async () => {
    const { container } = render(
      <ConfirmDialog open title="Suspend" body="y" onConfirm={() => {}} onCancel={() => {}} />
    );
    await expectAxeToHaveNoViolations(container);
  });
});