import { expect, test } from "@playwright/test";
import { DEMO_ORG_ID, expectNoA11yViolations, loginAsPlatform } from "./fixtures";

test.describe("Control Center — flujo smoke", () => {
  test("login → overview → tenants → tenant 360 → impersonate → exit → logout", async ({ page }) => {
    // Login de plataforma
    await loginAsPlatform(page);
    await expect(page.getByRole("heading", { name: "Economía de la plataforma" })).toBeVisible();
    await expectNoA11yViolations(page);

    // Tenants
    await page.goto("/control-center/tenants");
    await expect(page.getByRole("heading", { name: "Clientes" })).toBeVisible();

    // Tenant 360
    await page.goto(`/control-center/tenants/${DEMO_ORG_ID}`);
    await expect(page.getByText(/Plan: /)).toBeVisible({ timeout: 20000 });

    // Tabs de la ficha
    await page.getByRole("tab", { name: "Billing" }).click();
    await page.getByRole("tab", { name: "Security" }).click();
    await page.getByRole("tab", { name: "Audit" }).click();
    await page.getByRole("tab", { name: "Overview" }).click();

    // Impersonación (requiere motivo; expira en 1h)
    await page.getByRole("button", { name: /Impersonar.*privilegiada/ }).click();
    await expect(page.getByRole("alertdialog")).toBeVisible();
    await page.getByRole("button", { name: "Impersonar", exact: true }).click();
    await page.getByPlaceholder(/Soporte/).fill("E2E smoke: verificación de impersonación");
    await page.getByRole("button", { name: "Impersonar", exact: true }).click();
    await expect(page).toHaveURL(/\/$/);
    await expect(page.getByText(/Modo impersonación/)).toBeVisible({ timeout: 20000 });

    // Salir de impersonación
    await page.getByRole("button", { name: /Salir de impersonación/ }).click();
    await expect(page).toHaveURL(/\/control-center/);
    await expect(page.getByText(/Modo impersonación/)).toBeHidden({ timeout: 20000 });

    // Logout de plataforma
    await page.getByRole("button", { name: "Cerrar sesión" }).click();
    await expect(page).toHaveURL(/\/control-center\/login/);
  });

  test("switch de pantalla: Settings CC → portal como usuario → volver", async ({ page }) => {
    await loginAsPlatform(page);
    await page.goto("/control-center/settings");
    await expect(
      page.getByRole("heading", { name: "Cambio de pantalla (pruebas)" })
    ).toBeVisible();

    // Entra como usuario de la organización demo (preseleccionada).
    await page.getByRole("button", { name: "Entrar como usuario" }).click();
    await expect(page).toHaveURL(/\/$/, { timeout: 30_000 });
    await expect(page.getByText(/Modo impersonación/)).toBeVisible({ timeout: 20_000 });

    // Vuelta desde Configuración del portal.
    await page.goto("/settings");
    await expect(page.getByRole("heading", { name: "Control Center" })).toBeVisible();
    await page.getByRole("button", { name: "Volver al Control Center" }).click();
    await expect(page).toHaveURL(/\/control-center\/settings/, { timeout: 30_000 });
    await expect(page.getByText(/Modo impersonación/)).toBeHidden({ timeout: 20_000 });
  });
});