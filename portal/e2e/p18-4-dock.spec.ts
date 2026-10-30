import { expect, test } from "@playwright/test";
import { loginAsTenant, suppressProductTour } from "./fixtures";

const WORKFLOW_ID = process.env.E2E_DOCK_WORKFLOW_ID || "ef43a71c-87d1-4f8f-928a-e4f60dd5c1d3";

test.skip(!process.env.E2E_DOCK, "Requiere workflow local y E2E_DOCK=1");

test("el drawer conserva el resultado al cerrar y reabrir", async ({ page }) => {
  test.setTimeout(120_000);
  await suppressProductTour(page);
  await loginAsTenant(page);
  await page.setViewportSize({ width: 820, height: 900 });
  await page.goto(`/workflows/${WORKFLOW_ID}`);
  await expect(page.getByTestId("workflow-canvas-editor")).toBeVisible({ timeout: 30_000 });

  await page.getByTestId("wf-open-dock").click();
  await expect(page.getByTestId("wf-test-panel")).toBeVisible({ timeout: 20_000 });
  await page.getByTestId("wf-test-payload").fill("¿Sabes quién es el zorro?");
  await page.getByTestId("wf-test").click();
  await expect(page.getByTestId("wf-result-headline")).toBeVisible({ timeout: 45_000 });

  await page.getByRole("button", { name: "Cerrar panel" }).click();
  await expect(page.getByTestId("wf-test-panel")).toBeHidden();

  await page.getByTestId("wf-open-dock").click();
  await expect(page.getByTestId("wf-result-headline")).toBeVisible({ timeout: 20_000 });
});
