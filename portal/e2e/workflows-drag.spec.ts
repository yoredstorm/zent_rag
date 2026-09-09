import { expect, test } from "@playwright/test";
import { loginAsTenant, suppressProductTour } from "./fixtures";

// Regresión del arrastre del canvas: el bloque debe seguir al cursor con el
// delta exacto (bug histórico: se movía ~3× por coordenadas absolutas mal
// aplicadas).
test.describe("Canvas drag", () => {
  test("arrastrar un bloque sigue al cursor (delta exacto)", async ({ page }) => {
    await suppressProductTour(page);
    await loginAsTenant(page);
    await page.goto("/workflows");
    await expect(page.getByTestId("workflow-canvas-editor")).toBeVisible({ timeout: 20_000 });

    await page.getByPlaceholder("nombre…").fill("Drag Probe");
    await page.getByRole("button", { name: "Crear", exact: true }).click();
    await expect(async () => {
      const n = await page.getByTestId("wf-canvas-node").count();
      expect(n).toBeGreaterThanOrEqual(2);
    }).toPass({ timeout: 15_000 });

    const node = page.getByTestId("wf-canvas-node").first();
    const before = await node.boundingBox();
    expect(before).toBeTruthy();

    const cx = before!.x + before!.width / 2;
    const cy = before!.y + before!.height / 2;
    await page.mouse.move(cx, cy);
    await page.mouse.down();
    await page.mouse.move(cx + 120, cy + 60, { steps: 3 });
    await page.mouse.up();
    await page.waitForTimeout(300);

    const after = await node.boundingBox();
    expect(after).toBeTruthy();
    const dL = Math.round(after!.x - before!.x);
    const dT = Math.round(after!.y - before!.y);
    expect(Math.abs(dL - 120)).toBeLessThanOrEqual(4);
    expect(Math.abs(dT - 60)).toBeLessThanOrEqual(4);
  });
});