import { expect, test } from "@playwright/test";
import {
  DEMO_ORG_ID,
  DEV_API_KEY,
  loginAsTenant,
  suppressProductTour,
} from "./fixtures";

test.skip(!process.env.E2E_APPROVAL, "Requiere E2E_APPROVAL=1 y API local");

function approvalGraph() {
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
        id: "approval",
        type: "human_approval",
        version: 1,
        label: "Aprobar caso",
        position: { x: 280, y: 0 },
        config: { action: "Aprobar caso E2E", summary: "Revisar antes de continuar" },
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
      { id: "e1", from_node: "t", from_port: "out", to_node: "approval", to_port: "in" },
      { id: "e2", from_node: "approval", from_port: "out", to_node: "end", to_port: "in" },
    ],
    entrypoints: ["t"],
    variables: {},
    metadata: {},
  };
}

async function createApprovalWorkflow(request: import("@playwright/test").APIRequestContext) {
  const headers = {
    Authorization: `Bearer ${DEV_API_KEY}`,
    "X-Organization-Id": DEMO_ORG_ID,
  };
  const workspaces = await request.get("/api/v1/workspaces", { headers });
  expect(workspaces.ok()).toBeTruthy();
  const listing = await workspaces.json();
  const workspaceId = listing.workspaces[0].id;
  const created = await request.post("/api/v1/workflows", {
    headers: {
      ...headers,
      "X-Workspace-Id": workspaceId,
      "Idempotency-Key": `p18-4-approval-${Date.now()}`,
    },
    data: {
      name: `P18.4 Approval ${Date.now()}`,
      trigger_type: "webhook",
      steps: [],
      graph: approvalGraph(),
    },
  });
  expect(created.ok()).toBeTruthy();
  return (await created.json()).workflow_id as string;
}

test("human_approval se muestra como Esperando aprobación", async ({ page, request }) => {
  test.setTimeout(180_000);
  const workflowId = await createApprovalWorkflow(request);
  await suppressProductTour(page);
  await loginAsTenant(page);
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto(`/workflows/${workflowId}`);
  await expect(page.getByTestId("workflow-canvas-editor")).toBeVisible({ timeout: 30_000 });

  await page.getByTestId("wf-test-payload").fill("Caso de aprobación E2E");
  await page.getByText("Más acciones").click();
  await page.getByTestId("wf-run").click();
  const dialog = page.getByRole("dialog", { name: "Ejecutar workflow con efectos reales" });
  await expect(dialog).toBeVisible();
  await dialog.getByLabel("Escribe EJECUTAR para confirmar").fill("EJECUTAR");
  await dialog.getByRole("button", { name: "Ejecutar de verdad" }).click();

  const headline = page.getByTestId("wf-result-headline");
  await expect(headline).toBeVisible({ timeout: 60_000 });
  await expect(headline.getByText("Esperando aprobación")).toBeVisible();
  await expect(headline.getByText("La ejecución no terminó")).toBeVisible();
});
