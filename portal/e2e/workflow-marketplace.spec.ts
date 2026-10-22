import { expect, test } from "@playwright/test";
import { loginAsTenant, suppressProductTour } from "./fixtures";

test.describe("Marketplace-native workflow canvas", () => {
  test("biblioteca con marketplace, instalación inline sin salir del workflow y sugerencias", async ({ page }) => {
    await suppressProductTour(page);
    await loginAsTenant(page);
    await page.goto("/workflows");
    await expect(page.getByRole("heading", { name: "Workflow Automation" })).toBeVisible({ timeout: 30_000 });

    // Workflow nuevo en canvas: lista → modo manual → estudio.
    await page.getByTestId("wf-new-modes").click();
    await page.getByTestId("wf-mode-manual").click();
    await page.getByTestId("wf-new-name").fill("E2E Mkt Canvas");
    await page.getByTestId("wf-create").click();
    await expect(page.getByTestId("workflow-canvas-editor")).toBeVisible({ timeout: 20_000 });
    await expect(page.getByTestId("wf-node-library")).toBeVisible();

    await expect(page.getByTestId("wf-capabilities")).toBeVisible({ timeout: 20_000 });
    await expect(page.getByText("Agregar desde Marketplace")).toHaveCount(0);
    await expect(page.getByTestId("wf-mkt-drawer")).toHaveCount(0);
    const resolve = page.getByRole("link", { name: "Resolver en Marketplace global" });
    if (await resolve.count()) {
      const href = await resolve.first().getAttribute("href");
      expect(href ?? "").toContain("/marketplace");
      expect(href ?? "").not.toMatch(/^https?:/);
      await resolve.first().click();
      await expect(page).toHaveURL(/\/marketplace/, { timeout: 15_000 });
      await expect(page.getByText("Un solo catálogo")).toBeVisible();
      return;
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