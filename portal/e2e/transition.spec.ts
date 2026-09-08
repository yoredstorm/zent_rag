import { expect, test } from "@playwright/test";
import { loginAsTenant } from "./fixtures";

test.describe("Phase 31C trial transition", () => {
  test("signup sees demo banner and can start with my data", async ({ page }) => {
    const stamp = Date.now();
    const email = `e2e-31c-${stamp}@example.com`;
    const password = "Onboard123!";

    await page.goto("/signup");
    await page.getByLabel("Nombre de empresa").fill(`E2E Transition ${stamp}`);
    await page.getByLabel("Email").fill(email);
    await page.getByLabel("Contraseña", { exact: true }).fill(password);
    await page.getByLabel("Confirmar contraseña").fill(password);
    await page.getByRole("button", { name: "Empezar trial" }).click();

    await expect(page).toHaveURL(/\/$/, { timeout: 30_000 });
    const keyDialog = page.getByRole("dialog", { name: "Tu API key" });
    if (await keyDialog.isVisible().catch(() => false)) {
      await page.getByRole("button", { name: "Ya la guardé" }).click();
    }

    await expect(page.getByTestId("demo-banner")).toBeVisible({ timeout: 20_000 });
    await page.getByRole("link", { name: "Start with My Data" }).click();
    await expect(page.getByText("Create a clean business workspace")).toBeVisible();
    await page.getByRole("button", { name: "Continue" }).click();
    await expect(page.getByText("Welcome to your business workspace.")).toBeVisible();
    await expect(page.getByRole("link", { name: "Create a database with Zent" })).toBeVisible();
  });

  test("logged-in tenant can open transition page", async ({ page }) => {
    await loginAsTenant(page);
    await page.goto("/onboarding/transition");
    await expect(
      page.getByText(/Start with My Data|Welcome to your business workspace/i)
    ).toBeVisible({ timeout: 15000 });
  });
});
