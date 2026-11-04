import { expect, test, type Page } from "@playwright/test";
import { mockWorkflowStudio, openMockStudio } from "./workflowStudioMock";

/**
 * Interacción canvas-first sobre el backend simulado: paneles contextuales,
 * modo enfoque, búsqueda, viewport persistido, auto-layout deshacible,
 * simulador enlazado al lienzo y arrastre desde el catálogo.
 */
test.use({ viewport: { width: 1650, height: 922 } });

const canvas = (page: Page) => page.getByTestId("workflow-canvas");
const nodeById = (page: Page, id: string) => page.locator(`[data-testid="wf-canvas-node"][data-node-id="${id}"]`);

async function zoom(page: Page) {
  return Number(await canvas(page).getAttribute("data-zoom"));
}

async function nodeLeft(page: Page, id: string) {
  return nodeById(page, id).evaluate((el) => parseFloat((el as HTMLElement).style.left));
}

test.describe("Workflow Builder canvas-first: interacción", () => {
  test.beforeEach(async ({ page }) => {
    await mockWorkflowStudio(page);
    await openMockStudio(page);
  });

  test("catálogo bajo demanda e inspector al seleccionar, redimensionable y colapsable", async ({ page }) => {
    await expect(page.getByTestId("wf-node-library")).toHaveCount(0);
    await expect(page.getByTestId("wf-inspector")).toHaveCount(0);

    await page.getByTestId("wf-rail-add").click();
    const library = page.getByTestId("wf-node-library");
    await expect(library).toBeVisible();
    await expect(library.getByRole("searchbox").or(library.locator("input").first())).toBeFocused();
    await page.keyboard.press("Escape");
    await expect(library).toHaveCount(0);

    const before = await zoom(page);
    await nodeById(page, "precio").click();
    const inspector = page.getByTestId("wf-inspector");
    await expect(inspector).toBeVisible();
    await expect(inspector).toHaveAttribute("data-docked", "true");
    await expect(inspector).toContainText("Precio y stock");
    expect(await zoom(page)).toBe(before);

    await nodeById(page, "stock_ok").click();
    await expect(inspector).toContainText("¿Hay stock suficiente?");
    await expect
      .poll(async () => {
        const host = (await canvas(page).boundingBox())!;
        const n = (await nodeById(page, "stock_ok").boundingBox())!;
        return n.x >= host.x && n.x + n.width <= host.x + host.width;
      })
      .toBe(true);
    expect(await zoom(page)).toBe(before);

    const width = (await inspector.boundingBox())!.width;
    await page.getByTestId("wf-inspector-resize").focus();
    await page.keyboard.press("ArrowLeft");
    await page.keyboard.press("ArrowLeft");
    await expect.poll(async () => Math.round((await inspector.boundingBox())!.width)).toBe(Math.round(width + 32));

    await page.getByTestId("wf-inspector-collapse").click();
    await expect(page.getByTestId("wf-inspector-expand")).toBeVisible();
    await page.getByTestId("wf-inspector-expand").click();
    await expect(page.getByTestId("wf-node-config")).toBeVisible();
  });

  test("modo enfoque oculta la interfaz, Esc sale y restaura paneles y viewport", async ({ page }) => {
    await page.getByTestId("wf-open-dock").click();
    await expect(page.getByTestId("wf-simulator")).toHaveAttribute("data-state", "open");
    await page.getByTestId("wf-zoom-in").click();
    const z = await zoom(page);

    await page.getByTestId("wf-focus-toggle").click();
    await expect(page.getByTestId("wf-studio-header")).toBeHidden();
    await expect(page.getByTestId("wf-simulator")).toBeHidden();
    await expect(page.getByTestId("wf-focus-exit")).toBeVisible();
    const box = (await canvas(page).boundingBox())!;
    expect(box.width).toBeGreaterThanOrEqual(1650 - 2);
    expect(box.height).toBeGreaterThanOrEqual(922 - 2);
    expect(await page.evaluate(() => document.fullscreenElement)).toBeNull();

    await canvas(page).click({ position: { x: 5, y: 5 } });
    await page.keyboard.press("Escape");
    await expect(page.getByTestId("wf-studio-header")).toBeVisible();
    await expect(page.getByTestId("wf-simulator")).toHaveAttribute("data-state", "open");
    await expect.poll(() => zoom(page)).toBe(z);
  });

  test("Ctrl+F busca un nodo, lo selecciona y lo trae a la vista", async ({ page }) => {
    await canvas(page).click({ position: { x: 5, y: 5 } });
    await page.keyboard.press("Control+f");
    await page.getByTestId("wf-canvas-search-input").fill("historial");
    await expect(page.getByTestId("wf-canvas-search-hit").first()).toContainText("Pedidos del cliente");
    await page.keyboard.press("Enter");
    await expect(page.getByTestId("wf-inspector")).toContainText("Pedidos del cliente");

    const host = (await canvas(page).boundingBox())!;
    const node = (await nodeById(page, "historial").boundingBox())!;
    expect(node.x).toBeGreaterThanOrEqual(host.x);
    expect(node.x + node.width).toBeLessThanOrEqual(host.x + host.width);
    expect(node.y).toBeGreaterThanOrEqual(host.y);
    expect(node.y + node.height).toBeLessThanOrEqual(host.y + host.height);
  });

  test("el viewport se conserva al recargar y abrir paneles no reencuadra", async ({ page }) => {
    await page.getByTestId("wf-zoom-in").click();
    await page.getByTestId("wf-zoom-in").click();
    const z = await zoom(page);
    await page.getByTestId("wf-rail-add").click();
    await page.getByTestId("wf-open-dock").click();
    expect(await zoom(page)).toBe(z);

    await page.waitForTimeout(400);
    await openMockStudio(page);
    await expect.poll(() => zoom(page)).toBe(z);
    await expect(page.getByTestId("wf-zoom-level")).toHaveText(`${Math.round(z * 100)}%`);
  });

  test("ordenar en vertical cambia la disposición y Deshacer la recupera", async ({ page }) => {
    const x0 = await nodeLeft(page, "stock_ok");
    const edgeIds = () =>
      page.locator("[data-edge-id]").evaluateAll((els) => els.map((el) => el.getAttribute("data-edge-id")).sort());
    const edges = await edgeIds();
    expect(edges.length).toBeGreaterThan(20);
    await page.getByTestId("wf-autolayout").click();
    await page.getByTestId("wf-autolayout-tb").click();
    await expect.poll(() => nodeLeft(page, "stock_ok")).not.toBe(x0);
    expect(await edgeIds()).toEqual(edges);

    await page.getByTestId("wf-undo").click();
    await expect.poll(() => nodeLeft(page, "stock_ok")).toBe(x0);
  });

  test("un paso del simulador lleva a su nodo en el lienzo", async ({ page }) => {
    await page.getByTestId("wf-open-dock").click();
    await page.getByTestId("wf-test-payload").fill("Quiero 2 unidades");
    await page.getByTestId("wf-test").click();
    const trace = page.getByTestId("wf-trace");
    await expect(trace.getByTestId("wf-trace-step").first()).toBeVisible({ timeout: 20_000 });
    await expect(trace.getByTestId("wf-trace-step").first()).toContainText("Falta configurar la consulta de historial");

    await trace.getByTestId("wf-trace-step").first().click();
    await expect(page.getByTestId("wf-inspector")).toContainText("¿Hay stock suficiente?");
    await expect(nodeById(page, "stock_ok")).toHaveAttribute("aria-pressed", "true");
  });

  test("arrastrar un nodo del catálogo lo crea donde se suelta", async ({ page }) => {
    const count = await page.getByTestId("wf-canvas-node").count();
    await page.getByTestId("wf-rail-add").click();
    const item = page.locator('[data-testid^="wf-add-"]').first();
    await expect(item).toBeVisible();
    const host = (await canvas(page).boundingBox())!;
    await item.dragTo(canvas(page), { targetPosition: { x: host.width / 2, y: host.height - 120 } });
    await expect(page.getByTestId("wf-canvas-node")).toHaveCount(count + 1);
    await expect(page.getByTestId("wf-inspector")).toBeVisible();
  });
});
