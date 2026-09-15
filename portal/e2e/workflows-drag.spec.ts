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

    await page.getByTestId("wf-new-modes").click();
    await page.getByTestId("wf-mode-manual").click();
    await page.getByTestId("wf-new-name").fill("Drag Probe");
    await page.getByTestId("wf-create").click();
    await expect(page.getByTestId("workflow-canvas-editor")).toBeVisible({ timeout: 20_000 });

    await expect(async () => {
      const n = await page.getByTestId("wf-canvas-node").count();
      expect(n).toBeGreaterThanOrEqual(2);
    }).toPass({ timeout: 15_000 });

    const nodes = page.getByTestId("wf-canvas-node");
    const node = nodes.first();
    const anchor = nodes.nth(1);
    // Centra el nodo para que el arrastre no salga del lienzo (si el pointer
    // abandona el contenedor, el handler deja de recibir moves).
    await node.evaluate((el) => (el as HTMLElement).scrollIntoView({ block: "center", inline: "center" }));
    await page.waitForTimeout(300);
    // Posición relativa a otro nodo: el pan del lienzo (y cualquier auto-pan por
    // selección) mueve ambos por igual, así que se cancela.
    const relativePos = async () => {
      const a = await node.boundingBox();
      const b = await anchor.boundingBox();
      expect(a && b).toBeTruthy();
      return { dx: a!.x - b!.x, dy: a!.y - b!.y };
    };
    const before = await relativePos();
    const box = await node.boundingBox();
    expect(box).toBeTruthy();

    const cx = box!.x + box!.width / 2;
    const cy = box!.y + box!.height / 2;
    await page.mouse.move(cx, cy);
    await page.mouse.down();
    await page.mouse.move(cx + 120, cy + 60, { steps: 3 });
    await page.mouse.up();
    await page.waitForTimeout(400);

    const after = await relativePos();
    const dL = Math.round(after.dx - before.dx);
    const dT = Math.round(after.dy - before.dy);
    expect(Math.abs(dL - 120)).toBeLessThanOrEqual(4);
    expect(Math.abs(dT - 60)).toBeLessThanOrEqual(4);
  });
});