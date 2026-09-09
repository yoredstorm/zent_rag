import { expect, test } from "@playwright/test";
import { expectNoA11yViolations, loginAsTenant } from "./fixtures";

test.describe("Product tour — panel cliente", () => {
  test("auto-start, siguiente, saltar y no reabre al recargar", async ({ page }) => {
    await loginAsTenant(page, { skipTour: false });
    const dialog = page.getByRole("dialog");
    await expect(dialog).toBeVisible();
    await expect(dialog.getByRole("heading", { name: "Panel general" })).toBeVisible();
    await expectNoA11yViolations(page);

    await page.getByRole("button", { name: "Siguiente" }).click();
    await expect(dialog.getByRole("heading", { name: "Construir" })).toBeVisible();

    await page.getByRole("button", { name: "Siguiente" }).click();
    await expect(dialog.getByRole("heading", { name: "Playground" })).toBeVisible();

    await page.getByRole("button", { name: "Saltar" }).click();
    await expect(dialog).toHaveCount(0);

    await page.reload();
    await expect(page.getByRole("heading", { name: "Panel general" })).toBeVisible();
    await expect(page.getByRole("dialog")).toHaveCount(0);
  });

  test("menú Ver tutorial reabre el tour", async ({ page }) => {
    await loginAsTenant(page);
    await expect(page.getByRole("dialog")).toHaveCount(0);

    await page.getByRole("button", { name: "Cuenta" }).click();
    await page.getByRole("menuitem", { name: "Ver tutorial" }).click();

    const dialog = page.getByRole("dialog");
    await expect(dialog).toBeVisible();
    await expect(dialog.getByRole("heading", { name: "Panel general" })).toBeVisible();
  });
});
