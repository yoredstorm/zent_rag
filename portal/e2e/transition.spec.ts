import { expect, test } from "@playwright/test";
import { loginAsTenant, suppressProductTour, completeStartMode } from "./fixtures";

test.describe("Phase 31C trial transition", () => {
  test("signup sees demo banner and can start with my data", async ({ page }) => {
    const stamp = Date.now();
    const email = `e2e-31c-${stamp}@example.com`;
    const password = "Onboard123!";

    await suppressProductTour(page);
    await page.goto("/signup");
    await page.getByLabel("Nombre de empresa").fill(`E2E Transition ${stamp}`);
    await page.getByLabel("Email").fill(email);
    await page.getByLabel("Contraseña", { exact: true }).fill(password);
    await page.getByLabel("Confirmar contraseña").fill(password);
    await page.getByRole("button", { name: "Empezar trial" }).click();

    await completeStartMode(page, "demo");
    await expect(page.getByTestId("demo-banner")).toBeVisible({ timeout: 20_000 });
    await expect(page.getByText("Estás explorando Zent con datos de prueba.")).toBeVisible();
    const keyDialog = page.getByRole("dialog", { name: "Tu API key" });
    if (await keyDialog.isVisible().catch(() => false)) {
      await page.getByRole("button", { name: "Ya la guardé" }).click();
      await expect(keyDialog).toBeHidden();
    }
    await page.getByRole("link", { name: "Empezar con mis datos" }).click();
    await expect(page.getByText("Crear un espacio de negocio vacío")).toBeVisible();
    await page.getByRole("button", { name: "Continuar" }).click();
    await expect(page.getByText("Bienvenido a tu espacio de negocio.")).toBeVisible();
    await expect(page.getByRole("link", { name: "Crear una base de datos con Zent" })).toBeVisible();
  });

  test("logged-in tenant can open transition page", async ({ page }) => {
    await loginAsTenant(page);
    await page.goto("/onboarding/transition");
    await expect(
      page.getByText(/Empezar con mis datos|Bienvenido a tu espacio de negocio/i)
    ).toBeVisible({ timeout: 15000 });
  });
});
