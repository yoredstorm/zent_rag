import { expect, test } from "@playwright/test";
import { loginAsTenant, suppressProductTour } from "./fixtures";

test.describe("Workflows Canvas", () => {
  test("crear workflow en canvas, agregar nodo, guardar y dry-run", async ({ page }) => {
    await suppressProductTour(page);
    await loginAsTenant(page);
    await page.goto("/workflows");
    await expect(page.getByRole("heading", { name: "Workflow Automation" })).toBeVisible({ timeout: 20_000 });
    await expect(page.getByTestId("workflow-canvas-editor")).toBeVisible();
    await expect(page.getByTestId("wf-node-library")).toBeVisible();
    await expect(page.getByTestId("wf-android-contract")).toBeVisible();

    // Crear workflow nuevo en canvas: trigger + nodo fin → 2 nodos.
    await page.getByPlaceholder("nombre…").fill("E2E Canvas Flow");
    await page.getByRole("button", { name: "Crear", exact: true }).click();
    await expect(async () => {
      const n = await page.getByTestId("wf-canvas-node").count();
      expect(n).toBeGreaterThanOrEqual(2);
    }).toPass({ timeout: 15_000 });

    // Agregar un nodo desde la biblioteca (IA → llm).
    await page.getByTestId("wf-add-llm").click();
    await expect(async () => {
      const n = await page.getByTestId("wf-canvas-node").count();
      expect(n).toBeGreaterThanOrEqual(3);
    }).toPass({ timeout: 10_000 });
    await expect(page.getByText("Preguntar a un agente").first()).toBeVisible({ timeout: 10_000 });

    // Conectar trigger → llm arrastrando desde el puerto de salida.
    const triggerNode = page.getByTestId("wf-canvas-node").filter({ hasText: "Webhook" }).first();
    const llmNode = page.getByTestId("wf-canvas-node").filter({ hasText: "Preguntar a un agente" }).first();
    const outBox = await triggerNode.getByLabel("Conectar salida out").boundingBox();
    const inBox = await llmNode.getByLabel("Entrada in").boundingBox();
    expect(outBox).toBeTruthy();
    expect(inBox).toBeTruthy();
    await page.mouse.move(outBox!.x + 6, outBox!.y + 6);
    await page.mouse.down();
    await page.mouse.move(inBox!.x + 6, inBox!.y + 6, { steps: 10 });
    await page.mouse.up();

    // Guardar persiste el grafo v2.
    await page.getByTestId("wf-save").click();
    await expect(page.getByText(/Guardado/).first()).toBeVisible({ timeout: 15_000 });

    // Dry-run: nodos con efecto se simulan (llm planificado) sin ejecutar nada.
    await page.getByTestId("wf-test").click();
    await expect(page.getByText(/Dry-run/).first()).toBeVisible({ timeout: 20_000 });
    await expect(page.getByTestId("wf-run-inspector")).toBeVisible({ timeout: 15_000 });
    await expect(page.getByText(/efectos planeados/i).first()).toBeVisible({ timeout: 10_000 });

    // Ejecutar en serio: run con estado final en el inspector.
    await page.getByTestId("wf-run").click();
    await expect(page.getByText(/Run: /).first()).toBeVisible({ timeout: 20_000 });
    await expect(page.getByTestId("wf-run-inspector")).toBeVisible({ timeout: 15_000 });
  });

  test("instala plantilla stock y la lista la muestra", async ({ page }) => {
    await suppressProductTour(page);
    await loginAsTenant(page);
    await page.goto("/workflows");
    await expect(page.getByRole("heading", { name: "Workflow Automation" })).toBeVisible({ timeout: 20_000 });

    const install = page.getByTestId("wf-install-low-stock-alert");
    if (await install.isVisible()) {
      await install.click();
      await expect(
        page.getByRole("button", { name: "Alerta de stock bajo" }).first()
      ).toBeVisible({ timeout: 15_000 });
    }
  });
});