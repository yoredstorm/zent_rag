import { expect, test } from "@playwright/test";
import { loginAsTenant, suppressProductTour, completeStartMode } from "./fixtures";

test.describe("Phase 31C trial transition", () => {
  test("signup lands on an empty workspace and can create a business space", async ({ page }) => {
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

    await completeStartMode(page);

    // Sin demo: el alta aterriza en el panel vacío y no hay banner de datos de prueba.
    await expect(page.getByTestId("demo-banner")).toHaveCount(0);
    await expect(page.getByRole("heading", { name: "Bienvenido a Zent" })).toBeVisible({
      timeout: 20_000,
    });
    const keyDialog = page.getByRole("dialog", { name: "Tu API key" });
    if (await keyDialog.isVisible().catch(() => false)) {
      await page.getByRole("button", { name: "Ya la guardé" }).click();
      await expect(keyDialog).toBeHidden();
    }

    // El espacio de negocio se puede crear desde el asistente de transición.
    await page.goto("/onboarding/transition");
    await expect(page.getByText("Crear un espacio de negocio vacío")).toBeVisible({
      timeout: 20_000,
    });
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
