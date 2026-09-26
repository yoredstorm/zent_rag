import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import LoginPage from "./Login";

const LOGIN = vi.hoisted(() => vi.fn());
const PLATFORM_LOGIN = vi.hoisted(() => vi.fn());
const API = vi.hoisted(() => vi.fn());

vi.mock("../auth", () => ({
  useAuth: () => ({ session: null, ready: true, login: LOGIN, signup: vi.fn(), logout: vi.fn() }),
}));
vi.mock("../platformAuth", () => ({ usePlatformAuth: () => ({ login: PLATFORM_LOGIN }) }));
vi.mock("../api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../api")>();
  return { ...actual, api: API };
});
// El shell es ambiente (campo de conocimiento con animaciones infinitas): se
// reemplaza por un contenedor para que estos tests midan el formulario y no
// consuman CPU que necesita el resto de la suite en paralelo.
vi.mock("../components/auth/AuthShell", () => ({
  AuthShell: ({ title, children }: { title: string; children: React.ReactNode }) => (
    <div>
      <h1>{title}</h1>
      {children}
    </div>
  ),
}));

function renderLogin() {
  return render(
    <MemoryRouter>
      <LoginPage />
    </MemoryRouter>
  );
}

/** Llena el formulario por el camino del DOM: sin esperas de animación. */
function fill(email: string, password: string) {
  fireEvent.change(screen.getByLabelText("Email"), { target: { value: email } });
  fireEvent.change(screen.getByLabelText("Contraseña"), { target: { value: password } });
}

beforeEach(() => {
  LOGIN.mockReset().mockResolvedValue(undefined);
  PLATFORM_LOGIN.mockReset().mockResolvedValue(undefined);
  API.mockReset().mockResolvedValue({});
});

afterEach(() => {
  vi.restoreAllMocks();
});

describe("login", () => {
  it("presenta las etiquetas y el CTA del formulario", () => {
    renderLogin();
    expect(screen.getByLabelText("Email")).toBeInTheDocument();
    expect(screen.getByLabelText("Contraseña")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Continuar" })).toBeInTheDocument();
  });

  it("pide los datos que faltan en vez de llamar a la API", async () => {
    const user = userEvent.setup({ delay: null });
    renderLogin();

    await user.click(screen.getByRole("button", { name: "Continuar" }));

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Completá tu email y contraseña para entrar."
    );
    expect(LOGIN).not.toHaveBeenCalled();
    expect(screen.getByLabelText("Email")).toHaveFocus();
  });

  it("envía las credenciales normalizadas", async () => {
    const user = userEvent.setup({ delay: null });
    renderLogin();

    fill("  demo@zenttech.com ", "clave");
    await user.click(screen.getByRole("button", { name: "Continuar" }));

    await waitFor(() =>
      expect(LOGIN).toHaveBeenCalledWith("demo@zenttech.com", "clave")
    );
  });

  it("acepta lo tipeado a mano en el campo de contraseña", async () => {
    const user = userEvent.setup({ delay: null });
    renderLogin();

    fill("demo@zenttech.com", "");
    await user.type(screen.getByLabelText("Contraseña"), "ab");
    await user.click(screen.getByRole("button", { name: "Continuar" }));

    await waitFor(() => expect(LOGIN).toHaveBeenCalledWith("demo@zenttech.com", "ab"));
  });

  it("marca el CTA como ocupado y bloquea los campos mientras entra", async () => {
    let release: (() => void) | undefined;
    LOGIN.mockImplementation(
      () =>
        new Promise<void>((resolve) => {
          release = () => resolve();
        })
    );
    const user = userEvent.setup({ delay: null });
    renderLogin();

    fill("demo@zenttech.com", "clave");
    await user.click(screen.getByRole("button", { name: "Continuar" }));

    const busy = await screen.findByRole("button", { name: /Entrando/ });
    expect(busy).toHaveAttribute("aria-busy", "true");
    expect(screen.getByLabelText("Email")).toBeDisabled();
    expect(screen.getByRole("status", { name: "Verificando credenciales" })).toBeInTheDocument();

    release?.();
    await waitFor(() => expect(screen.getByLabelText("Email")).toBeEnabled());
  });

  it("muestra el error del backend sin descartar el formulario", async () => {
    LOGIN.mockRejectedValue(new Error("Credenciales inválidas"));
    const user = userEvent.setup({ delay: null });
    renderLogin();

    fill("demo@zenttech.com", "mala");
    await user.click(screen.getByRole("button", { name: "Continuar" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("Credenciales inválidas");
    expect(screen.getByLabelText("Email")).toBeEnabled();
    expect(screen.getByRole("button", { name: "Continuar" })).toBeInTheDocument();
  });

  it("traduce el código del backend a un mensaje legible", async () => {
    LOGIN.mockRejectedValue(new Error("invalid_credentials Invalid email or password."));
    const user = userEvent.setup({ delay: null });
    renderLogin();

    fill("demo@zenttech.com", "mala");
    await user.click(screen.getByRole("button", { name: "Continuar" }));

    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("Email o contraseña incorrectos");
    expect(alert).not.toHaveTextContent("invalid_credentials");
  });

  it("entra por el Control Center si la cuenta es de plataforma", async () => {
    LOGIN.mockRejectedValue(new Error("platform_login_required"));
    const user = userEvent.setup({ delay: null });
    renderLogin();

    fill("admin@zent.dev", "clave");
    await user.click(screen.getByRole("button", { name: "Continuar" }));

    await waitFor(() => expect(PLATFORM_LOGIN).toHaveBeenCalledTimes(1));
    expect(screen.queryByRole("alert")).toBeNull();
  });

  it("abre y cierra el panel de restablecimiento", async () => {
    const user = userEvent.setup({ delay: null });
    renderLogin();

    const toggle = screen.getByRole("button", { name: /Olvidé mi contraseña/ });
    expect(toggle).toHaveAttribute("aria-expanded", "false");

    await user.click(toggle);

    expect(toggle).toHaveAttribute("aria-expanded", "true");
    expect(
      screen.getByText("Te enviamos un enlace de restablecimiento al email de la cuenta.")
    ).toBeInTheDocument();

    await user.click(toggle);
    expect(toggle).toHaveAttribute("aria-expanded", "false");
  });

  it("pide el email antes de mandar el enlace", async () => {
    const user = userEvent.setup({ delay: null });
    renderLogin();

    await user.click(screen.getByRole("button", { name: /Olvidé mi contraseña/ }));
    await user.click(screen.getByRole("button", { name: "Enviar enlace" }));

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Escribí tu email y te enviamos el enlace."
    );
    expect(API).not.toHaveBeenCalled();
  });

  it("avisa cuando Bloq Mayús está activado", async () => {
    renderLogin();
    const password = screen.getByLabelText("Contraseña");

    const caps = vi.spyOn(KeyboardEvent.prototype, "getModifierState").mockReturnValue(true);
    fireEvent.keyDown(password, { key: "A" });

    expect(await screen.findByText("Bloq Mayús está activado")).toBeInTheDocument();
    expect(password).toHaveAccessibleDescription("Bloq Mayús está activado");

    caps.mockReturnValue(false);
    fireEvent.blur(password);
    await waitFor(() => expect(screen.queryByText("Bloq Mayús está activado")).toBeNull());
    expect(password).not.toHaveAttribute("aria-describedby");
  });
});
