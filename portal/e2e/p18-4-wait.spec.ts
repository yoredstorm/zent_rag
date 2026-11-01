import { expect, test } from "@playwright/test";
import { DEMO_ORG_ID, DEV_EMAIL, DEV_PASSWORD, loginAsTenant, suppressProductTour } from "./fixtures";

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
      { id: "e2", from_node: "wait", from_port: "out", to_node: "end", to_port: "in" },
    ],
    entrypoints: ["t"],
    variables: {},
    metadata: {},
  };
}

test("wait_event espera señal y reanuda la instancia", async ({ page, request }) => {
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
      name: `P18.4 Wait ${Date.now()}`,
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
  await page.goto(`/workflows/${workflowId}`);
  await expect(page.getByTestId("workflow-canvas-editor")).toBeVisible({ timeout: 30_000 });

  await page.getByTestId("wf-test-payload").fill("Caso de espera E2E");
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
  const runId = runBody.run?.run_id as string;
  expect(instanceId).toBeTruthy();
  expect(runId).toBeTruthy();

  const headline = page.getByTestId("wf-result-headline");
  await expect(headline).toBeVisible({ timeout: 60_000 });
  await expect(headline.getByText("Esperando mensaje")).toBeVisible();
  await expect(headline.getByText("El flujo quedó en espera")).toBeVisible();

  const signal = await request.post(`/api/v1/workflows/instances/${instanceId}/signal`, {
    headers: { ...headers, "Content-Type": "application/json" },
    data: { event_type: "signal", payload: { message: "continuar" } },
  });
  expect(signal.ok()).toBeTruthy();
  const signalBody = await signal.json();
  expect(signalBody.resumed).toBe(true);

  await expect
    .poll(
      async () => {
        const detail = await request.get(`/api/v1/workflows/instances/${instanceId}`, { headers });
        if (!detail.ok()) return `http_${detail.status()}`;
        return (await detail.json()).status as string;
      },
      { timeout: 30_000 },
    )
    .toBe("COMPLETED");

  const instance = await request.get(`/api/v1/workflows/instances/${instanceId}`, { headers });
  const resumedRunId = (await instance.json()).last_run_id as string;
  expect(resumedRunId).not.toBe(runId);
  const resumed = await request.get(`/api/v1/workflows/runs/${resumedRunId}`, { headers });
  expect(resumed.ok()).toBeTruthy();
  expect((await resumed.json()).status).toBe("succeeded");
});
