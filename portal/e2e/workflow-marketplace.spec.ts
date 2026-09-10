import { expect, test } from "@playwright/test";
import { loginAsTenant, suppressProductTour } from "./fixtures";

test.describe("Marketplace-native workflow canvas", () => {
  test("biblioteca con marketplace, instalación inline sin salir del workflow y sugerencias", async ({ page }) => {
    await suppressProductTour(page);
    await loginAsTenant(page);
    await page.goto("/workflows");
    await expect(page.getByRole("heading", { name: "Workflow Automation" })).toBeVisible({ timeout: 30_000 });

    // Workflow nuevo en canvas.
    await page.getByPlaceholder("nombre…").fill("E2E Mkt Canvas");
    await page.getByRole("button", { name: "Crear", exact: true }).click();
    await expect(page.getByTestId("workflow-canvas-editor")).toBeVisible({ timeout: 20_000 });
    await expect(page.getByTestId("wf-node-library")).toBeVisible();

    // Sección Marketplace presente (disponible: demo-echo del seed).
    await expect(page.getByTestId("wf-mkt-section")).toBeVisible({ timeout: 20_000 });
    const installBtn = page.getByTestId("wf-mkt-install-demo-echo");
    if (await installBtn.count()) {
      await installBtn.click();
      await expect(page.getByTestId("wf-mkt-drawer")).toBeVisible({ timeout: 10_000 });
      await expect(page.getByTestId("wf-mkt-install-confirm")).toBeVisible();
      await page.getByTestId("wf-mkt-install-confirm").click();
      // Tras instalar, la acción queda disponible sin recargar el canvas.
      await expect(page.getByTestId("wf-mkt-action-demo.echo")).toBeVisible({ timeout: 15_000 });
      await page.getByTestId("wf-mkt-action-demo.echo").click();
      await expect(async () => {
        const n = await page.getByTestId("wf-canvas-node").count();
        expect(n).toBeGreaterThanOrEqual(2);
      }).toPass({ timeout: 10_000 });
    }

    // RENIEC (datos personales): pedir propósito y confirmar el flujo de error claro.
    const reniec = page.getByTestId("wf-mkt-install-reniec-verification");
    if (await reniec.count()) {
      await reniec.click();
      await expect(page.getByTestId("wf-mkt-drawer")).toBeVisible({ timeout: 10_000 });
      await page.getByTestId("wf-mkt-install-confirm").click();
      await expect(page.getByText(/propósito/i).first()).toBeVisible({ timeout: 15_000 });
      await page.getByTestId("wf-mkt-purpose").fill("Verificación de clientes (e2e)");
      await page.getByTestId("wf-mkt-install-confirm").click();
      await expect(page.getByTestId("wf-mkt-action-peru.identity.verify")).toBeVisible({ timeout: 15_000 });
    }

    // Sugerencia de automatización para canvas vacío.
    const hint = page.getByTestId("wf-empty-hint");
    if (await hint.count()) {
      await expect(hint.getByText("¿Qué quieres automatizar?")).toBeVisible();
      await page.getByTestId("wf-suggest-verify").click();
      await expect(async () => {
        const n = await page.getByTestId("wf-canvas-node").count();
        expect(n).toBeGreaterThanOrEqual(3);
      }).toPass({ timeout: 10_000 });
    }
  });
});