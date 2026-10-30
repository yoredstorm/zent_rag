import { expect, test } from "@playwright/test";
import { loginAsTenant, suppressProductTour } from "./fixtures";

const WORKFLOW_ID = process.env.E2E_MODES_WORKFLOW_ID || "ef43a71c-87d1-4f8f-928a-e4f60dd5c1d3";

test.skip(!process.env.E2E_MODES, "Requiere workflow local y E2E_MODES=1");

test("preview y proveedor capeado no llaman a /run", async ({ page }) => {
  test.setTimeout(180_000);
  await suppressProductTour(page);
  await loginAsTenant(page);
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto(`/workflows/${WORKFLOW_ID}`);
  await expect(page.getByTestId("workflow-canvas-editor")).toBeVisible({ timeout: 30_000 });

  const calls: string[] = [];
  page.on("request", (request) => calls.push(request.url()));

  await page.getByTestId("wf-level-preview").click();
  await page.getByTestId("wf-test").click();
  await expect(page.getByText("Vista previa completada")).toBeVisible({ timeout: 45_000 });
  expect(calls.some((url) => url.endsWith("/run"))).toBe(false);

  await page.getByTestId("wf-modify-test").click();
  await page.getByTestId("wf-mode-real").click();
  await page.getByTestId("wf-level-provider").click();
  await page.getByTestId("wf-test-payload").fill("¿Sabes quién es el zorro?");
  await page.getByTestId("wf-test").click();
  await expect(page.getByText("Sin verificación de proveedor")).toBeVisible({ timeout: 45_000 });
  await expect(page.getByText("UNVERIFIED").first()).toBeVisible();
  await expect(page.getByText("Verificado por proveedor")).toHaveCount(0);
  expect(calls.some((url) => url.endsWith("/run"))).toBe(false);

  await page.getByTestId("wf-modify-test").click();
  await page.getByText("Más acciones").click();
  await page.getByTestId("wf-run").click();
  await expect(page.getByRole("dialog", { name: "Ejecutar workflow con efectos reales" })).toBeVisible();
  await page.getByRole("button", { name: "Cancelar" }).click();
  expect(calls.some((url) => url.endsWith("/run"))).toBe(false);
});
