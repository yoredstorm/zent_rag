import { expect, test } from "@playwright/test";
import { apiAsTenant, loginAsTenant, suppressProductTour } from "./fixtures";

function markerNode(id: string, type: string, config: Record<string, unknown>) {
  return {
    id,
    type,
    label: type,
    config,
    version: 1,
    metadata: {},
    position: {},
    timeout_ms: 60_000,
    input_ports: [{ name: "in", type: "json", required: true }],
    output_ports: [{ name: "out", type: "json" }],
    retry_policy: { max_attempts: 1 },
    error_policy: "fail",
  };
}

function markerGraph(value: string) {
  return {
    workflow_version: 2,
    variables: {},
    entrypoints: ["t"],
    metadata: {},
    nodes: [
      markerNode("t", "trigger_webhook", {}),
      markerNode("m", "set_variable", { name: "marker", value }),
      markerNode("end", "end", {}),
    ],
    edges: [
      {
        id: "e1",
        from_node: "t",
        from_port: "out",
        to_node: "m",
        to_port: "in",
        condition: null,
      },
      {
        id: "e2",
        from_node: "m",
        from_port: "out",
        to_node: "end",
        to_port: "in",
        condition: null,
      },
    ],
  };
}

test.describe("Publicación inmutable P13", () => {
  test("A sigue ejecutando tras editar B; publicar B cambia la versión", async ({
    page,
    request,
  }) => {
    await suppressProductTour(page);

    const created = await apiAsTenant(request, "/workflows", {
      method: "POST",
      body: JSON.stringify({
        name: `E2E P13 ${Date.now()}`,
        trigger_type: "webhook",
        graph: markerGraph("A"),
        workflow_version: 2,
      }),
    });
    if (!created.ok()) {
      console.log("create failed", created.status(), await created.text());
    }
    expect(created.ok()).toBeTruthy();
    const workflow = (await created.json()) as {
      workflow_id: string;
      hook_secret: string;
    };

    const certified = await apiAsTenant(
      request,
      `/workflows/${workflow.workflow_id}/certifications`,
      { method: "POST", body: JSON.stringify({ level: "design" }) },
    );
    expect(certified.ok()).toBeTruthy();
    const published = await apiAsTenant(
      request,
      `/workflows/${workflow.workflow_id}/publish`,
      { method: "POST", body: JSON.stringify({}) },
    );
    expect(published.ok()).toBeTruthy();

    // PATCH B: el draft cambia, la versión publicada no.
    const patched = await apiAsTenant(
      request,
      `/workflows/${workflow.workflow_id}`,
      { method: "PATCH", body: JSON.stringify({ graph: markerGraph("B"), workflow_version: 2 }) },
    );
    expect(patched.ok()).toBeTruthy();

    const hook = await request.post(
      `/api/v1/public/workflows/${workflow.workflow_id}/hook`,
      {
        headers: { "X-Zent-Workflow-Secret": workflow.hook_secret },
        data: { message: "same" },
      },
    );
    expect(hook.ok()).toBeTruthy();
    const hookBody = (await hook.json()) as { run_id: string };

    const run = await apiAsTenant(request, `/workflows/runs/${hookBody.run_id}`);
    expect(run.ok()).toBeTruthy();
    const runBody = (await run.json()) as {
      steps: { node_id?: string; output?: { value?: string } }[];
    };
    const marker = runBody.steps.find((step) => step.node_id === "m");
    expect(marker?.output?.value).toBe("A");

    await loginAsTenant(page);
    await page.goto(`/workflows/${workflow.workflow_id}`);
    await page.getByTestId("wf-open-advanced").click();
    await expect(page.getByTestId("wf-advanced-panel")).toBeVisible({ timeout: 20_000 });
    await expect(page.getByTestId("wf-published-banner")).toContainText("Versión activa v1");
    await expect(page.getByTestId("wf-published-banner")).toContainText(
      "cambios sin publicar",
    );

    // Certificar B y publicar desde la UI.
    const recertified = await apiAsTenant(
      request,
      `/workflows/${workflow.workflow_id}/certifications`,
      { method: "POST", body: JSON.stringify({ level: "design" }) },
    );
    expect(recertified.ok()).toBeTruthy();
    await page.goto(`/workflows/${workflow.workflow_id}?panel=advanced`);
    await expect(page.getByTestId("wf-advanced-panel")).toBeVisible({
      timeout: 20_000,
    });
    await expect(page.getByTestId("wf-publish")).toBeEnabled({ timeout: 20_000 });
    const [publishResponse] = await Promise.all([
      page.waitForResponse(
        (response) =>
          response.url().includes(`/workflows/${workflow.workflow_id}/publish`) &&
          response.request().method() === "POST",
      ),
      page.getByTestId("wf-publish").click(),
    ]);
    expect(publishResponse.ok()).toBeTruthy();
    await page.goto(`/workflows/${workflow.workflow_id}?panel=advanced`);
    await expect(page.getByTestId("wf-published-banner")).toContainText(
      "Versión activa v2",
      { timeout: 20_000 },
    );
  });
});
