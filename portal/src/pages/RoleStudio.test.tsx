import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";
import RoleStudioPage from "./RoleStudio";

const AUTH = vi.hoisted(() => ({
  session: { token: "rag_sess_t", organizationId: "org-1", roles: ["owner"], permissions: [] },
}));
const API = vi.hoisted(() => ({ api: vi.fn() }));

vi.mock("../auth", () => ({ useAuth: () => AUTH }));
vi.mock("../api", () => ({ api: API.api }));

const TEMPLATE = {
  role_id: "mentor",
  name: "Mentor",
};

const ROLE = {
  record_id: "",
  schema: "zent.role/v1",
  role_id: "mentor",
  version: "1.0.0",
  status: "draft",
  name: "Mentor de práctica",
  description: "Orienta con práctica medible.",
  mission: "Ayudar a convertir objetivos en práctica concreta y medible.",
  audience: ["profesionales"],
  tone: ["directo"],
  competencies: [{ name: "plan de práctica" }],
  constraints: ["No promete resultados."],
  allowed_capabilities: ["knowledge_query"],
  denied_capabilities: [],
  allowed_tools: ["search_knowledge"],
  knowledge_scope: { kinds: ["knowledge_base"] },
  memory_policy: { scope: "session" },
  autonomy_level: "propose_actions",
  human_handoff: { triggers: ["riesgo"], destination: "human" },
  expected_outcomes: [{ name: "plan", metric: "sesiones_con_plan", target: "> 0" }],
  evaluation_rubric: [],
  risk_class: "low",
  locales: ["es"],
  compliance_tags: [],
  safety: { no_automatic_irreversible_action: true },
};

const SHEET = {
  role_id: "mentor",
  name: "Mentor de práctica",
  mission: ROLE.mission,
  will_do: ["plan de práctica"],
  will_not_do: ["No promete resultados.", "No ejecuta acciones irreversibles sin aprobación."],
  autonomy_level: "propose_actions",
  handoff: ROLE.human_handoff,
  outcomes: ROLE.expected_outcomes,
  disclaimer: "",
};

function stubApi() {
  API.api.mockImplementation(async (path: string, options?: RequestInit) => {
    if (path === "/api/v1/studio/templates") {
      return { templates: [TEMPLATE] };
    }
    if (path === "/api/v1/studio/roles" && (!options || !options.method)) {
      return { roles: [] };
    }
    if (path === "/api/v1/agents") {
      return { agents: [] };
    }
    if (path === "/api/v1/studio/roles/propose") {
      return {
        source: "template",
        template_id: "mentor",
        confidence: 0.6,
        role: ROLE,
        mission_sheet: SHEET,
        workflow_proposal: {
          workflow_ref: "mentor_flow",
          name: "Ciclo de mentoría",
          trigger: "conversation",
          design_steps: ["definir objetivo", "plan de práctica", "revisar avance"],
        },
        requires_review: true,
        publishable: false,
      };
    }
    if (path === "/api/v1/studio/roles" && options?.method === "POST") {
      return { role: { ...ROLE, record_id: "role-1" }, mission_sheet: SHEET };
    }
    return {};
  });
}

afterEach(() => {
  API.api.mockReset();
});

describe("RoleStudioPage", () => {
  it("propone un rol y muestra qué hará y qué no hará antes de guardar", async () => {
    stubApi();
    render(
      <MemoryRouter>
        <RoleStudioPage />
      </MemoryRouter>,
    );

    expect(await screen.findByRole("heading", { name: "Roles" })).toBeInTheDocument();
    expect(await screen.findByText(/Aún no hay roles/)).toBeInTheDocument();

    await userEvent.type(
      screen.getByTestId("role-prompt"),
      "Un mentor para práctica profesional",
    );
    await userEvent.click(screen.getByRole("button", { name: /Proponer rol/ }));

    await waitFor(() => expect(screen.getByTestId("role-review")).toBeInTheDocument());
    expect(screen.getByTestId("mission-sheet")).toBeInTheDocument();
    expect(screen.getByText("Hará")).toBeInTheDocument();
    expect(screen.getByText("No hará")).toBeInTheDocument();
    expect(screen.getAllByText(/No promete resultados/).length).toBeGreaterThan(0);
    expect(screen.getByText(/No ejecuta acciones irreversibles sin aprobación/)).toBeInTheDocument();
    expect(screen.getByText(/Autonomía efectiva/)).toBeInTheDocument();
    expect(screen.getByText("Métricas")).toBeInTheDocument();
    expect(screen.getByTestId("workflow-proposal")).toBeInTheDocument();
    expect(screen.getByText("Ciclo de mentoría")).toBeInTheDocument();

    await userEvent.click(screen.getByTestId("save-role"));
    await waitFor(() =>
      expect(API.api).toHaveBeenCalledWith(
        "/api/v1/studio/roles",
        expect.objectContaining({ method: "POST" }),
      ),
    );

    await userEvent.click(screen.getByRole("button", { name: /Crear solución borrador/ }));
    await waitFor(() =>
      expect(API.api).toHaveBeenCalledWith(
        "/api/v1/studio/solutions",
        expect.objectContaining({ method: "POST" }),
      ),
    );
  });

  it("mantiene la creación asistida como borrador editable", async () => {
    stubApi();
    render(
      <MemoryRouter>
        <RoleStudioPage />
      </MemoryRouter>,
    );
    await screen.findByText(/Todavía no hay una hoja de misión/);
    expect(screen.getByText(/No se publica nada hasta que la revises/)).toBeInTheDocument();
  });
});
