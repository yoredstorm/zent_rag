import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { AxeBuilder } from "@axe-core/playwright";
import { expect, test } from "@playwright/test";
import { loginAsTenant, suppressProductTour } from "./fixtures";

const WORKFLOW_ID = process.env.E2E_VISUAL_WORKFLOW_ID || "ef43a71c-87d1-4f8f-928a-e4f60dd5c1d3";
const CAPTURES = path.resolve(
  path.dirname(fileURLToPath(import.meta.url)),
  "../../docs/architecture/workflow-test-ux-p18-4/captures",
);

async function shot(page: import("@playwright/test").Page, name: string) {
  fs.mkdirSync(CAPTURES, { recursive: true });
  await page.waitForTimeout(450);
  await page.screenshot({ path: path.join(CAPTURES, name), fullPage: false });
}

async function ready(page: import("@playwright/test").Page) {
  await expect(page.getByTestId("workflow-canvas-editor")).toBeVisible({ timeout: 30_000 });
}

async function expectPanelA11y(page: import("@playwright/test").Page) {
  const results = await new AxeBuilder({ page })
    .include('[data-testid="wf-test-panel"]')
    .disableRules(["scrollable-region-focusable"])
    .analyze();
  const serious = results.violations.filter((v) => v.impact === "serious" || v.impact === "critical");
  if (serious.length > 0) {
    const summary = serious
      .map((v) => `${v.id}: ${v.help} (${v.impact}) - ${v.nodes.map((n) => n.target.join(" ")).join(" | ")}`)
      .join("\n");
    expect.soft(false, `Violaciones de accesibilidad del panel:\n${summary}`).toBeTruthy();
  }
}

async function openDock(page: import("@playwright/test").Page) {
  const open = page.getByTestId("wf-open-dock");
  if (await open.isVisible()) await open.click();
  await expect(page.getByTestId("wf-test-panel")).toBeVisible({ timeout: 20_000 });
}

test.describe("P18.4 visual capture", () => {
  test.skip(!process.env.E2E_VISUAL, "Solo captura visual explícita");

  test("captura setup y resultado en desktop, tablet y móvil", async ({ page }) => {
    test.setTimeout(240_000);
    await suppressProductTour(page);
    await loginAsTenant(page);
    await page.evaluate(() => localStorage.setItem("zent_theme", "dark"));

    await page.setViewportSize({ width: 1440, height: 900 });
    await page.goto(`/workflows/${WORKFLOW_ID}`);
    await ready(page);
    await shot(page, "1440-setup-dark.png");
    await expectPanelA11y(page);

    await page.getByTestId("wf-test-payload").fill("¿Sabes quién es el zorro?");
    await page.getByTestId("wf-test").click();
    await expect(page.getByTestId("wf-result-headline")).toBeVisible({ timeout: 45_000 });
    await shot(page, "1440-result-dark.png");
    await expectPanelA11y(page);

    await page.getByTestId("wf-modify-test").click();
    await page.getByTestId("wf-mode-real").click();
    await page.getByTestId("wf-level-provider").click();
    await page.getByTestId("wf-test").click();
    await expect(page.getByTestId("wf-result-headline")).toBeVisible({ timeout: 45_000 });
    await shot(page, "1440-provider-capped-dark.png");

    await page.evaluate(() => localStorage.setItem("zent_theme", "light"));
    await page.reload();
    await ready(page);
    await shot(page, "1440-setup-light.png");
    await page.getByTestId("wf-test-payload").fill("¿Sabes quién es el zorro?");
    await page.getByTestId("wf-test").click();
    await expect(page.getByTestId("wf-result-headline")).toBeVisible({ timeout: 45_000 });
    await shot(page, "1440-result-light.png");

    await page.setViewportSize({ width: 820, height: 900 });
    await page.evaluate(() => localStorage.setItem("zent_theme", "dark"));
    await page.reload();
    await ready(page);
    await openDock(page);
    await shot(page, "820-setup-dark.png");

    await page.setViewportSize({ width: 390, height: 844 });
    await page.reload();
    await ready(page);
    await openDock(page);
    await shot(page, "390-setup-dark.png");
    await expectPanelA11y(page);
    await page.getByTestId("wf-test-payload").fill("¿Sabes quién es el zorro?");
    await page.getByTestId("wf-test").click();
    await expect(page.getByTestId("wf-result-headline")).toBeVisible({ timeout: 45_000 });
    await shot(page, "390-result-dark.png");
  });
});
