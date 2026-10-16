import { expect, test } from "@playwright/test";
import { loginAsPlatform, loginAsTenant, suppressProductTour } from "./fixtures";

test.describe("Marketplace Factory", () => {
  test("tenant: catálogo unificado y biblioteca de instalados", async ({ page }) => {
    await suppressProductTour(page);
    await loginAsTenant(page);
    // /products quedó como alias del marketplace global.
    await page.goto("/products");
    await expect(page).toHaveURL(/\/marketplace$/);
    await expect(page.getByRole("heading", { name: "Marketplace" })).toBeVisible({ timeout: 20_000 });
    await expect(page.getByTestId("marketplace-grid")).toBeVisible({ timeout: 20_000 });
    await page.getByRole("tab", { name: /Instalados/ }).click();
    await expect(page.getByTestId("marketplace-installed")).toBeVisible({ timeout: 10_000 });
  });

  test("control center: overview de la factory y lista de productos", async ({ page }) => {
    await loginAsPlatform(page);
    await page.goto("/control-center/marketplace-factory");
    await expect(page.getByRole("heading", { name: "Marketplace Factory" })).toBeVisible({ timeout: 20_000 });
    await expect(page.getByTestId("factory-overview")).toBeVisible({ timeout: 20_000 });
    await page.getByRole("button", { name: "Products", exact: true }).click();
    await expect(page.getByTestId("factory-products")).toBeVisible({ timeout: 10_000 });
    await expect(page.getByRole("button", { name: "Nuevo producto" })).toBeVisible();
  });
});