import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";
import DemoCenterPage from "./DemoCenter";

const AUTH = vi.hoisted(() => ({
  session: { token: "rag_sess_t", organizationId: "org-1", roles: ["owner"], permissions: [] },
}));
const NAVIGATE = vi.hoisted(() => vi.fn());

vi.mock("../auth", () => ({ useAuth: () => AUTH }));
vi.mock("react-router-dom", async (importOriginal) => {
  const actual = await importOriginal<typeof import("react-router-dom")>();
  return { ...actual, useNavigate: () => NAVIGATE };
});

const TEMPLATES = [
  {
    slug: "pokemon-analyst",
    name: "Analizar un Pokémon",
    description: "Consulta PokéAPI y pide un resumen.",
    category: "demo",
    trigger_type: "webhook",
    steps: [],
  },
  {
    slug: "weather-heat-alert",
    name: "Alerta de calor (Lima)",
    description: "Avisa si Lima supera 30 °C.",
    category: "demo",
    trigger_type: "schedule",
    steps: [],
  },
  {
    slug: "high-value-sale",
    name: "Venta importante",
    description: "No es demo.",
    category: "sales",
    trigger_type: "event",
    steps: [],
  },
];

function json(body: unknown) {
  return new Response(JSON.stringify(body), { status: 200, headers: { "Content-Type": "application/json" } });
}

function stubApi() {
  vi.stubGlobal(
    "fetch",
    vi.fn((input: RequestInfo | URL) => {
      const url = String(input);
      if (url.includes("/templates/weather-heat-alert/install")) {
        return Promise.resolve(json({ workflow_id: "wf-7" }));
      }
      if (url.endsWith("/workflows/templates")) return Promise.resolve(json({ templates: TEMPLATES }));
      return Promise.resolve(json({}));
    }),
  );
}

afterEach(() => {
  vi.unstubAllGlobals();
  NAVIGATE.mockReset();
});

describe("DemoCenterPage", () => {
  it("muestra solo recetas demo y marca las deterministas", async () => {
    stubApi();
    render(<MemoryRouter><DemoCenterPage /></MemoryRouter>);
    await waitFor(() => expect(screen.getByTestId("demo-pokemon-analyst")).toBeInTheDocument());
    expect(screen.getByTestId("demo-weather-heat-alert")).toBeInTheDocument();
    expect(screen.getByTestId("demo-deterministic")).toHaveTextContent("sin IA");
    expect(screen.queryByTestId("demo-high-value-sale")).toBeNull();
  });

  it("probar instala la receta y abre el estudio en modo prueba", async () => {
    stubApi();
    const user = userEvent.setup();
    render(<MemoryRouter><DemoCenterPage /></MemoryRouter>);
    await waitFor(() => expect(screen.getByTestId("demo-start-weather-heat-alert")).toBeInTheDocument());
    await user.click(screen.getByTestId("demo-start-weather-heat-alert"));
    await waitFor(() =>
      expect(NAVIGATE).toHaveBeenCalledWith(
        "/workflows/wf-7?panel=test",
        expect.anything(),
      ),
    );
  });
});
