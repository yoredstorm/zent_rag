import { devices, expect, test, type Page } from "@playwright/test";

/**
 * Tutorial en el celular: el menú vive en el drawer y el tour lo abre para
 * señalar cada item. El drawer abría su dialog modal de Radix por encima del
 * tutorial (body con `pointer-events: none` + `aria-hidden` sobre la app), así
 * que no se podía avanzar ni saltar. La sesión se simula para que el caso
 * corra sin backend.
 */
test.use({ ...devices["Pixel 5"] });

const SESSION_ME = {
  organization_id: "00000000-0000-0000-0000-000000000001",
  company_name: "Acme",
  email: "demo@zenttech.com",
  roles: ["owner"],
  permissions: ["admin:*"],
  active_workspace_id: null,
  workspace_kind: "demo",
  needs_start_mode: false,
};

async function mockSession(page: Page) {
  // El resto de la API no es parte del caso: respuestas vacías, nunca 401
  // (un 401 cierra la sesión). Los handlers específicos van al final: la
  // última ruta registrada gana.
  await page.route("**/api/v1/**", (route) => route.fulfill({ json: {} }));
  await page.route("**/api/v1/auth/login", (route) =>
    route.fulfill({
      json: {
        access_token: "rag_sess_e2e_mobile",
        organization_id: SESSION_ME.organization_id,
        company_name: SESSION_ME.company_name,
        email: SESSION_ME.email,
      },
    })
  );
  await page.route("**/api/v1/auth/me", (route) => route.fulfill({ json: SESSION_ME }));
}

test.describe("Product tour — móvil con el drawer abierto", () => {
  test.afterEach(async ({ page }, testInfo) => {
    if (testInfo.status !== testInfo.expectedStatus) {
      await page.screenshot({ path: testInfo.outputPath("failure.png") }).catch(() => {});
    }
  });

  test("avanza, salta y no tapa el item señalado", async ({ page }) => {
    await mockSession(page);
    await page.goto("/login");
    await page.getByLabel("Email").fill(SESSION_ME.email);
    await page.getByLabel("Contraseña").fill("demo-password-change-me");
    await page.getByRole("button", { name: "Continuar" }).click();

    const card = page.getByTestId("product-tour");
    await expect(card.getByRole("heading", { name: "Panel general" })).toBeVisible();
    // El menú está abierto detrás del tutorial: el tutorial manda, no el drawer.
    await expect(page.getByRole("dialog", { name: "Menú de navegación" })).toBeVisible();

    // El item señalado queda visible por encima de la tarjeta (anclada abajo).
    const item = await page.locator('[data-tour="nav-dashboard"]:visible').boundingBox();
    const box = await card.locator('[role="dialog"]').boundingBox();
    expect(item, "el item señalado existe en el drawer").not.toBeNull();
    expect(box, "la tarjeta del tutorial está en pantalla").not.toBeNull();
    expect(item!.y + item!.height).toBeLessThanOrEqual(box!.y + 1);

    await page.screenshot({ path: "test-results/tour-mobile-drawer.png" });

    await page.getByRole("button", { name: "Siguiente" }).click();
    await expect(card.getByRole("heading", { name: "Construir" })).toBeVisible();

    await page.getByRole("button", { name: "Saltar" }).click();
    await expect(card).toHaveCount(0);
    // El drawer lo abrió el tutorial: se cierra con él.
    await expect(page.getByRole("dialog", { name: "Menú de navegación" })).toHaveCount(0);
  });

  test("el menú móvil reabre el tutorial", async ({ page }) => {
    // En el celular el menú de cuenta (que tiene "Ver tutorial") no existe:
    // el acceso vive en el drawer.
    await page.addInitScript(() => {
      localStorage.setItem("zent_product_tour_v2", JSON.stringify({ status: "skipped" }));
    });
    await mockSession(page);
    await page.goto("/login");
    await page.getByLabel("Email").fill(SESSION_ME.email);
    await page.getByLabel("Contraseña").fill("demo-password-change-me");
    await page.getByRole("button", { name: "Continuar" }).click();

    const card = page.getByTestId("product-tour");
    await expect(card).toHaveCount(0);

    await page.getByRole("button", { name: "Abrir menú" }).click();
    await page.getByRole("button", { name: "Ver tutorial" }).click();
    await expect(card.getByRole("heading", { name: "Panel general" })).toBeVisible();

    await page.getByRole("button", { name: "Siguiente" }).click();
    await expect(card.getByRole("heading", { name: "Construir" })).toBeVisible();
  });
});
