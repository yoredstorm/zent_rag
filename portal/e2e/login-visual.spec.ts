import { expect, test, type Page } from "@playwright/test";

/**
 * Regresión visual del acceso.
 *
 * Los baselines viven en `e2e/login-visual.spec.ts-snapshots/` y se generaron
 * en Linux con la imagen oficial de Playwright: el renderizado de texto cambia
 * entre plataformas. Por eso el spec sólo corre en CI o con `VISUAL=1`.
 *
 * La escena se captura con `prefers-reduced-motion`: el canvas queda en su
 * frame curado, determinista por seed, así el diff no depende de la animación.
 */
const enabled = Boolean(process.env.CI) || process.env.VISUAL === "1";

const SESSION = {
  organization_id: "org_visual",
  company_name: "Zent Visual",
  email: "visual@zent.dev",
  roles: ["owner"],
  permissions: [],
  active_workspace_id: "ws_visual",
  workspace_kind: "business",
  needs_start_mode: false,
};

async function mockApi(page: Page) {
  await page.route("**/api/**", (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({ items: [], ...SESSION }),
    })
  );
}

const VIEWPORTS = [
  { name: "desktop", width: 1440, height: 900 },
  { name: "laptop", width: 1366, height: 768 },
  { name: "mobile", width: 390, height: 844 },
];

test.describe("acceso: regresión visual", () => {
  test.skip(!enabled, "Baselines generadas en Linux: correr en CI o con VISUAL=1.");
  test.use({ reducedMotion: "reduce", locale: "es-PE" });

  for (const viewport of VIEWPORTS) {
    test(`login ${viewport.name}`, async ({ page }) => {
      await page.setViewportSize({ width: viewport.width, height: viewport.height });
      await mockApi(page);
      await page.goto("/login");
      await page.waitForSelector(".auth-card-shell");
      await page.evaluate(() => document.fonts.ready.then(() => undefined));
      await page.waitForTimeout(1300);
      await expect(page).toHaveScreenshot(`login-${viewport.name}.png`, {
        animations: "disabled",
        caret: "hide",
        maxDiffPixelRatio: 0.02,
        threshold: 0.2,
      });
    });
  }
});
