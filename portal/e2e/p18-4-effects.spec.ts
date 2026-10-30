import { expect, test } from "@playwright/test";
import { DEMO_ORG_ID, DEV_EMAIL, DEV_PASSWORD, loginAsTenant, suppressProductTour } from "./fixtures";

test.skip(!process.env.E2E_EFFECTS, "Requiere E2E_EFFECTS=1 y API local");

function effectGraph() {
  return {
    workflow_version: 2,
    nodes: [
      {
        id: "t",
        type: "trigger_webhook",
        version: 1,
        label: "Inicio",
        position: { x: 0, y: 0 },
        config: {},
        input_ports: [],
        output_ports: [{ name: "out", type: "json" }],
        retry_policy: { max_attempts: 1 },
        timeout_ms: 60000,
        error_policy: "fail",
        metadata: {},
      },
      {
        id: "notify",
        type: "notify",
        version: 1,
        label: "Avisar",
        position: { x: 280, y: 0 },
        config: {
          channel: "in_app",
          title: "P18.4 E2E",
          message: "Efecto real de prueba del Test Studio",
        },
        input_ports: [{ name: "in", type: "json" }],
        output_ports: [{ name: "out", type: "json" }],
        retry_policy: { max_attempts: 1 },
        timeout_ms: 60000,
        error_policy: "fail",
        metadata: {},
      },
      {
        id: "end",
        type: "end",
        version: 1,
        label: "Fin",
        position: { x: 560, y: 0 },
        config: {},
        input_ports: [{ name: "in", type: "json" }],
        output_ports: [],
        retry_policy: { max_attempts: 1 },
        timeout_ms: 60000,
        error_policy: "fail",
        metadata: {},
      },
    ],
    edges: [
      { id: "e1", from_node: "t", from_port: "out", to_node: "notify", to_port: "in" },
      { id: "e2", from_node: "notify", from_port: "out", to_node: "end", to_port: "in" },
    ],
    entrypoints: ["t"],
    variables: {},
    metadata: {},
  };
}

test("efecto real solo corre tras confirmar EJECUTAR", async ({ page, request }) => {
  test.setTimeout(180_000);
  const login = await request.post("/api/v1/auth/login", {
    data: { email: DEV_EMAIL, password: DEV_PASSWORD },
  });
  expect(login.ok()).toBeTruthy();
  const { access_token } = await login.json();
  const auth = {
    Authorization: `Bearer ${access_token}`,
    "X-Organization-Id": DEMO_ORG_ID,
  };
  const workspaces = await request.get("/api/v1/workspaces", { headers: auth });
  expect(workspaces.ok()).toBeTruthy();
  const workspaceId = (await workspaces.json()).workspaces[0].id as string;
  const headers = { ...auth, "X-Workspace-Id": workspaceId };
  const created = await request.post("/api/v1/workflows", {
    headers: { ...headers, "Content-Type": "application/json" },
    data: {
      name: `P18.4 Effects ${Date.now()}`,
      trigger_type: "webhook",
      steps: [],
      graph: effectGraph(),
    },
  });
  expect(created.ok()).toBeTruthy();
  const workflowId = (await created.json()).workflow_id as string;

  await suppressProductTour(page);
  await loginAsTenant(page);
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto(`/workflows/${workflowId}`);
  await expect(page.getByTestId("workflow-canvas-editor")).toBeVisible({ timeout: 30_000 });

  await page.getByTestId("wf-test-payload").fill("Caso de efecto real E2E");
  await page.getByText("Más acciones").click();
  await page.getByTestId("wf-run").click();
  const dialog = page.getByRole("dialog", { name: "Ejecutar workflow con efectos reales" });
  await expect(dialog).toBeVisible();
  await dialog.getByLabel("Escribe EJECUTAR para confirmar").fill("EJECUTAR");

  const runResponse = page.waitForResponse(
    (response) => response.url().endsWith("/run") && response.request().method() === "POST",
  );
  await dialog.getByRole("button", { name: "Ejecutar de verdad" }).click();
  const runBody = await (await runResponse).json();
  const runId = (runBody.run_id ?? runBody.run?.run_id) as string;
  expect(runId).toBeTruthy();

  const headline = page.getByTestId("wf-result-headline");
  await expect(headline).toBeVisible({ timeout: 60_000 });
  await expect(headline.getByText("Ejecución completada")).toBeVisible();
  await expect(page.getByText("Operación real finalizada")).toBeVisible();

  const detail = await request.get(`/api/v1/workflows/runs/${runId}`, { headers });
  expect(detail.ok()).toBeTruthy();
  const run = await detail.json();
  expect(run.status).toBe("succeeded");
  expect(run.simulate).toBe(false);
  const notify = (run.steps as { node_type: string; status: string; output?: Record<string, unknown> }[]).find(
    (step) => step.node_type === "notify",
  );
  expect(notify?.status).toBe("succeeded");
  expect(notify?.output?.sent).toBe(true);
  expect((notify?.output?.result as Record<string, unknown> | undefined)?.in_app).toBe(true);
});
