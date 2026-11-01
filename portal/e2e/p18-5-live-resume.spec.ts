import { expect, test } from "@playwright/test";
import {
  DEMO_ORG_ID,
  DEV_EMAIL,
  DEV_PASSWORD,
  loginAsTenant,
  suppressProductTour,
} from "./fixtures";

test.skip(!process.env.E2E_WAIT, "Requiere E2E_WAIT=1 y API local");

function waitGraph() {
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
        id: "wait",
        type: "wait_event",
        version: 1,
        label: "Esperar señal",
        position: { x: 280, y: 0 },
        config: { preset: "signal", signal_name: "signal" },
        input_ports: [{ name: "in", type: "json" }],
        output_ports: [{ name: "out", type: "json" }],
        retry_policy: { max_attempts: 1 },
        timeout_ms: 60000,
        error_policy: "fail",
        metadata: {},
      },
      {
        id: "mark",
        type: "set_variable",
        version: 1,
        label: "Marcar reanudado",
        position: { x: 420, y: 0 },
        config: { name: "resumed", value: "si" },
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
      { id: "e1", from_node: "t", from_port: "out", to_node: "wait", to_port: "in" },
      { id: "e2", from_node: "wait", from_port: "out", to_node: "mark", to_port: "in" },
      { id: "e3", from_node: "mark", from_port: "out", to_node: "end", to_port: "in" },
    ],
    entrypoints: ["t"],
    variables: {},
    metadata: {},
  };
}

test("WAIT → señal → COMPLETED se observa sin refrescar y sin segundo /run", async ({
  page,
  request,
}) => {
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
      name: `P18.5 Live ${Date.now()}`,
      trigger_type: "webhook",
      steps: [],
      graph: waitGraph(),
    },
  });
  expect(created.ok()).toBeTruthy();
  const workflowId = (await created.json()).workflow_id as string;

  await suppressProductTour(page);
  await loginAsTenant(page);
  await page.setViewportSize({ width: 1440, height: 900 });
  let runPosts = 0;
  page.on("request", (req) => {
    if (req.method() === "POST" && req.url().endsWith("/run")) runPosts += 1;
  });
  await page.goto(`/workflows/${workflowId}`);
  await expect(page.getByTestId("workflow-canvas-editor")).toBeVisible({ timeout: 30_000 });

  await page.getByTestId("wf-test-payload").fill("Caso vivo P18.5");
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
  const instanceId = runBody.instance_id as string;
  expect(instanceId).toBeTruthy();

  const durable = page.getByTestId("wf-durable-status");
  await expect(durable).toContainText("En espera", { timeout: 60_000 });

  const signal = await request.post(`/api/v1/workflows/instances/${instanceId}/signal`, {
    headers: { ...headers, "Content-Type": "application/json" },
    data: { event_type: "signal", payload: { message: "continuar" } },
  });
  expect(signal.ok()).toBeTruthy();

  // Sin page.reload(): el polling autorizado debe observar el nuevo segmento.
  await expect(durable).toContainText("COMPLETED", { timeout: 90_000 });
  expect(runPosts).toBe(1);
});
