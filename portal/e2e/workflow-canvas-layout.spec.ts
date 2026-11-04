import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { expect, test, type Page } from "@playwright/test";
import { mockWorkflowStudio, openMockStudio } from "./workflowStudioMock";

/**
 * Canvas-first del Workflow Builder: capturas comparativas y métricas de
 * espacio útil del lienzo en las resoluciones objetivo, sobre el grafo de la
 * demo de pedidos (25 nodos) servido por un backend simulado.
 *
 * SHOT_PHASE=before solo captura (no exige los umbrales del rediseño).
 */
const here = path.dirname(fileURLToPath(import.meta.url));
const PHASE = process.env.SHOT_PHASE || "after";
const SHOTS_DIR = path.resolve(here, "..", "shots", "canvas-first");

const VIEWPORTS = [
  { width: 1920, height: 1080 },
  { width: 1650, height: 922 },
  { width: 1366, height: 768 },
  { width: 1024, height: 768 },
];

type Metrics = {
  viewport: { width: number; height: number };
  canvas: { width: number; height: number; widthRatio: number; heightRatio: number };
  library: number | null;
  testPanel: number | null;
  mission: number | null;
  header: number | null;
  docScroll: number;
};

async function measure(page: Page): Promise<Metrics> {
  return page.evaluate(() => {
    const box = (selector: string) => {
      const el = document.querySelector(selector);
      if (!el) return null;
      const rect = el.getBoundingClientRect();
      return rect.width === 0 && rect.height === 0 ? null : rect;
    };
    const canvas = box('[data-testid="workflow-canvas"]');
    const vw = window.innerWidth;
    const vh = window.innerHeight;
    return {
      viewport: { width: vw, height: vh },
      canvas: {
        width: Math.round(canvas?.width ?? 0),
        height: Math.round(canvas?.height ?? 0),
        widthRatio: Number(((canvas?.width ?? 0) / vw).toFixed(3)),
        heightRatio: Number(((canvas?.height ?? 0) / vh).toFixed(3)),
      },
      library: box('[data-testid="wf-node-library"]')?.width ?? null,
      testPanel: box('[data-testid="wf-test-panel"]')?.width ?? null,
      mission:
        box('[data-testid="wf-mission-disclosure"]')?.height ??
        box('[data-testid="wf-mission-summary"]')?.height ??
        null,
      header: box('[data-testid="wf-studio-header"]')?.height ?? null,
      docScroll: document.documentElement.scrollHeight - vh,
    };
  });
}

test.describe("Workflow Builder canvas-first: layout", () => {
  test("capturas y métricas por resolución", async ({ page }) => {
    test.setTimeout(180_000);
    fs.mkdirSync(SHOTS_DIR, { recursive: true });
    await mockWorkflowStudio(page);
    const all: Metrics[] = [];
    for (const viewport of VIEWPORTS) {
      await page.setViewportSize(viewport);
      await openMockStudio(page);
      await page.waitForTimeout(500);
      const metrics = await measure(page);
      all.push(metrics);
      await page.screenshot({
        path: path.join(SHOTS_DIR, `${PHASE}-${viewport.width}x${viewport.height}.png`),
      });
      if (PHASE !== "before") {
        expect(metrics.docScroll).toBeLessThanOrEqual(0);
        expect(metrics.library ?? 0).toBeLessThan(200);
        expect(metrics.testPanel).toBeNull();
        expect(metrics.mission ?? 0).toBeLessThanOrEqual(48);
        if (viewport.width >= 1366) {
          expect(metrics.canvas.heightRatio).toBeGreaterThanOrEqual(0.85);
          expect(metrics.canvas.widthRatio).toBeGreaterThanOrEqual(0.9);
        }
      }
    }
    fs.writeFileSync(path.join(SHOTS_DIR, `${PHASE}-metrics.json`), JSON.stringify(all, null, 2));
  });

  test("capturas de paneles contextuales (1650×922)", async ({ page }) => {
    test.skip(PHASE === "before", "Los paneles contextuales no existían antes del rediseño");
    test.setTimeout(120_000);
    fs.mkdirSync(SHOTS_DIR, { recursive: true });
    await mockWorkflowStudio(page);
    await page.setViewportSize({ width: 1650, height: 922 });
    await openMockStudio(page);
    await page.getByTestId("wf-fit-view").click();
    const save = (name: string) => page.screenshot({ path: path.join(SHOTS_DIR, `after-1650-${name}.png`) });

    await page.getByTestId("wf-rail-add").click();
    await expect(page.getByTestId("wf-node-library")).toBeVisible();
    await save("catalog");
    await page.keyboard.press("Escape");

    await page.locator('[data-testid="wf-canvas-node"][data-node-id="stock_ok"]').click();
    await expect(page.getByTestId("wf-inspector")).toBeVisible();
    await save("inspector");

    await page.getByTestId("wf-open-dock").click();
    await expect(page.getByTestId("wf-simulator")).toHaveAttribute("data-state", "open");
    await page.getByTestId("wf-test-payload").fill("Quiero 2 unidades");
    await page.getByTestId("wf-test").click();
    await expect(page.getByTestId("wf-trace-step").first()).toBeVisible({ timeout: 20_000 });
    await save("simulator");

    await page.getByTestId("wf-focus-toggle").click();
    await expect(page.getByTestId("wf-focus-exit")).toBeVisible();
    await save("focus");
  });
});
