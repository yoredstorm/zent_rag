import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import type { Page, Route } from "@playwright/test";

/**
 * Backend simulado para el Workflow Studio: sesión sembrada y todas las
 * llamadas `/api/**` respondidas en local. Los specs de layout/canvas no
 * dependen del rate limit por minuto del plan ni mutan datos reales.
 */
const here = path.dirname(fileURLToPath(import.meta.url));

export const MOCK_WORKFLOW_ID = "00000000-0000-4000-8000-00000000c0de";
const ORG_ID = "00000000-0000-0000-0000-000000000001";
const WORKSPACE_ID = "00000000-0000-4000-8000-0000000000aa";

export function orderDeliveryGraph(): Record<string, unknown> {
  return JSON.parse(fs.readFileSync(path.join(here, "fixtures", "order-delivery-graph.json"), "utf-8"));
}

export type StudioMock = {
  /** Grafo persistido (lo que devolvería el servidor). */
  graph: () => Record<string, unknown>;
  patches: () => number;
  runs: () => number;
};

function json(route: Route, body: unknown, status = 200) {
  return route.fulfill({ status, contentType: "application/json", body: JSON.stringify(body) });
}

export async function mockWorkflowStudio(
  page: Page,
  options: { graph?: Record<string, unknown>; status?: string } = {},
): Promise<StudioMock> {
  let graph = structuredClone(options.graph ?? orderDeliveryGraph());
  let updatedAt = new Date().toISOString();
  let patches = 0;
  let runs = 0;
  const status = options.status ?? "draft";

  await page.addInitScript(
    ({ org, ws }) => {
      localStorage.setItem("zent_product_tour_v2", JSON.stringify({ status: "completed" }));
      localStorage.setItem("rag_portal_org", org);
      localStorage.setItem("rag_portal_company", "ZentTech Demo");
      localStorage.setItem("rag_portal_email", "demo@zenttech.com");
      localStorage.setItem("rag_portal_roles", JSON.stringify(["owner"]));
      localStorage.setItem("rag_portal_permissions", JSON.stringify(["*"]));
      localStorage.setItem("rag_portal_workspace", ws);
      localStorage.setItem("rag_portal_workspace_kind", "production");
      sessionStorage.setItem("rag_portal_token", "e2e-mock-token");
    },
    { org: ORG_ID, ws: WORKSPACE_ID },
  );

  const detail = () => ({
    id: MOCK_WORKFLOW_ID,
    name: "Pedido con entrega",
    description: "Valida stock, decide entrega o recojo y pide aprobación",
    trigger_type: "event",
    trigger_config: {},
    steps: [],
    graph,
    graph_hash: "hash-draft",
    workflow_version: 2,
    status,
    editor_state: { mode: "canvas", config_level: "simple" },
    created_at: updatedAt,
    updated_at: updatedAt,
    has_hook_secret: false,
  });

  const runDetail = () => {
    const nodes = (graph.nodes as { id: string; type: string }[]) ?? [];
    return {
      id: "run-e2e-1",
      workflow_id: MOCK_WORKFLOW_ID,
      status: "simulated",
      simulate: true,
      started_at: new Date().toISOString(),
      duration_ms: 120,
      error: null,
      steps: nodes.slice(0, 4).map((n, index) => ({
        node_id: n.id,
        node_type: n.type,
        status: index === 3 ? "failed" : "simulated",
        duration_ms: 10 + index,
        output: index === 2 ? { text: "Stock disponible: 4 unidades" } : {},
        error: index === 3 ? "Falta configurar la consulta de historial" : null,
      })),
    };
  };

  await page.route("**/api/**", async (route) => {
    const request = route.request();
    const url = new URL(request.url());
    const p = url.pathname.replace(/^\/api\/v1/, "");
    const method = request.method();

    if (p === "/auth/me") {
      return json(route, {
        organization_id: ORG_ID,
        company_name: "ZentTech Demo",
        email: "demo@zenttech.com",
        roles: ["owner"],
        permissions: ["*"],
        active_workspace_id: WORKSPACE_ID,
        workspace_kind: "production",
        needs_start_mode: false,
        feature_flags: {},
      });
    }
    if (p === "/workspaces") {
      return json(route, {
        workspaces: [{ id: WORKSPACE_ID, name: "Producción", kind: "production", is_default: true }],
      });
    }
    if (p === `/workflows/${MOCK_WORKFLOW_ID}`) {
      if (method === "PATCH") {
        patches += 1;
        const body = request.postDataJSON() as { graph?: Record<string, unknown> };
        if (body.graph) graph = body.graph;
        updatedAt = new Date().toISOString();
        return json(route, { ok: true });
      }
      return json(route, detail());
    }
    if (p === `/workflows/${MOCK_WORKFLOW_ID}/pinned-data`) return json(route, { nodes: [] });
    if (p === `/workflows/${MOCK_WORKFLOW_ID}/readiness`) {
      return json(route, {
        ready: false,
        errors: 0,
        warnings: 1,
        checks: [
          { key: "trigger", label: "Inicio", status: "ok", message: "Trigger configurado" },
          { key: "data", label: "Datos", status: "warning", message: "Una consulta sin binding publicado" },
        ],
        node_issues: {},
      });
    }
    if (p === `/workflows/${MOCK_WORKFLOW_ID}/summary`) {
      return json(route, {
        text: "Cuando llega un pedido, valida stock e historial, decide entrega o recojo y pide aprobación del pago.",
        when: "Al recibir un pedido",
        steps: [],
      });
    }
    if (p === `/workflows/${MOCK_WORKFLOW_ID}/runs`) return json(route, { runs: [] });
    if (p === `/workflows/${MOCK_WORKFLOW_ID}/run` && method === "POST") {
      runs += 1;
      return json(route, { run_id: "run-e2e-1", status: "simulated" });
    }
    if (p === "/workflows/runs/run-e2e-1") return json(route, runDetail());
    if (p === `/workflows/${MOCK_WORKFLOW_ID}/test` && method === "POST") {
      runs += 1;
      return json(route, {
        test_report_id: "test-e2e-1",
        requested_level: "simulation",
        effective_level: "simulation",
        provider_verified: false,
        result: "FAILED",
        executed_nodes: runDetail().steps,
      });
    }
    if (p === "/agents") return json(route, { agents: [] });
    if (p === "/knowledge-bases") return json(route, { knowledge_bases: [] });
    if (p === "/integrations/installs") return json(route, { installs: [] });
    if (p === "/workflows/node-schemas") return json(route, { schemas: [] });
    if (p === "/notifications/unread-count") return json(route, { count: 0 });
    if (p.startsWith("/knowledge/sessions")) return json(route, { sessions: [] });
    if (method === "GET") return json(route, { detail: "mock: not found" }, 404);
    return json(route, { ok: true });
  });

  return { graph: () => graph, patches: () => patches, runs: () => runs };
}

/** Abre el estudio del workflow simulado y espera a que el grafo esté pintado. */
export async function openMockStudio(page: Page, minNodes = 20) {
  if (process.env.E2E_DEBUG) {
    page.on("pageerror", (error) => console.log("PAGEERROR", error.stack));
    page.on("console", (msg) => msg.type() === "error" && console.log("CONSOLE", msg.text()));
  }
  await page.goto(`/workflows/${MOCK_WORKFLOW_ID}`);
  await page.getByTestId("workflow-canvas-editor").waitFor({ state: "visible", timeout: 30_000 });
  await page.waitForFunction(
    (min) => document.querySelectorAll('[data-testid="wf-canvas-node"]').length >= min,
    minNodes,
    { timeout: 20_000 },
  );
}
