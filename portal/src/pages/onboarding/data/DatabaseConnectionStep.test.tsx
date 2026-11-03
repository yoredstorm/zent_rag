import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { DatabaseConnectionStep } from "./DatabaseConnectionStep";

function fillRequired() {
  const host = screen.getByLabelText("Host");
  const database = screen.getByLabelText("Base");
  const username = screen.getByLabelText("Usuario");
  const password = screen.getByLabelText("Contraseña");
  return { host, database, username, password };
}

describe("DatabaseConnectionStep", () => {
  it("bloquea host privado sin allowlist y permite autorizarlo", async () => {
    const user = userEvent.setup();
    const onSubmit = vi.fn();
    render(<DatabaseConnectionStep onSubmit={onSubmit} busy={false} />);

    const { host, database, username, password } = fillRequired();
    await user.type(host, "host.docker.internal");
    await user.type(database, "zent_external_mvp");
    await user.type(username, "p19_reader");
    await user.type(password, "secret");

    expect(screen.getByText(/Host privado detectado/i)).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Probar conexión" }));
    expect(onSubmit).not.toHaveBeenCalled();
    expect(screen.getByRole("alert")).toHaveTextContent(/Hosts permitidos/i);

    await user.click(screen.getByRole("button", { name: /Permitir host.docker.internal/i }));
    await user.click(screen.getByRole("button", { name: "Probar conexión" }));
    expect(onSubmit).toHaveBeenCalledTimes(1);
    const body = onSubmit.mock.calls[0][0] as Record<string, unknown>;
    const advanced = body.advanced as Record<string, unknown>;
    expect(advanced.ssrf_allowlist).toEqual(["host.docker.internal"]);
  });

  it("no exige allowlist para un host público", async () => {
    const user = userEvent.setup();
    const onSubmit = vi.fn();
    render(<DatabaseConnectionStep onSubmit={onSubmit} busy={false} />);
    const { host, database, username, password } = fillRequired();
    await user.type(host, "db.example.com");
    await user.type(database, "erp");
    await user.type(username, "zent");
    await user.type(password, "secret");
    await user.click(screen.getByRole("button", { name: "Probar conexión" }));
    expect(onSubmit).toHaveBeenCalledTimes(1);
  });
});
