import { expect, test } from "@playwright/test";
import { loginAsTenant, suppressProductTour } from "./fixtures";

test.describe("Workflows Blockly", () => {
  test("instala plantilla stock y muestra editor de bloques", async ({ page }) => {
    await suppressProductTour(page);
    await loginAsTenant(page);
    await page.goto("/workflows");
    await expect(page.getByRole("heading", { name: "Workflow Automation" })).toBeVisible({ timeout: 20_000 });
    await expect(page.getByTestId("workflow-block-editor")).toBeVisible();
    await expect(page.getByTestId("wf-android-contract")).toBeVisible();
    const install = page.getByTestId("wf-install-low-stock-alert");
    if (await install.isVisible()) {
      await install.click();
      await expect(
        page.getByRole("button", { name: "Alerta de stock bajo" }).first()
      ).toBeVisible({ timeout: 15_000 });
    }
  });
});
