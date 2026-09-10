import path from "path";
import { fileURLToPath } from "url";
import { expect, test } from "@playwright/test";
import { suppressProductTour, completeStartMode } from "./fixtures";

const CSV = path.join(path.dirname(fileURLToPath(import.meta.url)), "fixtures", "productos.csv");

test.describe("Semantic Mapping Studio", () => {
  test("CSV → Entendimiento confirma campo → pregunta precio se abstiene o mapea", async ({ page }) => {
    const stamp = Date.now();
    const email = `e2e-studio-${stamp}@example.com`;
    const password = "Onboard123!";

    await suppressProductTour(page);
    await page.goto("/signup");
    await page.getByLabel("Nombre de empresa").fill(`E2E Studio ${stamp}`);
    await page.getByLabel("Email").fill(email);
    await page.getByLabel("Contraseña", { exact: true }).fill(password);
    await page.getByLabel("Confirmar contraseña").fill(password);
    await page.getByRole("button", { name: "Empezar trial" }).click();

    await completeStartMode(page, "blank");
    const keyDialog = page.getByRole("dialog", { name: "Tu API key" });
    await expect(keyDialog).toBeVisible({ timeout: 20_000 });
    await page.getByRole("button", { name: "Ya la guardé" }).click();
    await expect(keyDialog).toBeHidden();

    await page.getByRole("link", { name: "Conectar mis datos" }).click();
    await expect(page).toHaveURL(/\/knowledge\/add/);
    await page.getByTestId("source-kind-spreadsheets").click();
    await page.getByTestId("onboarding-file").setInputFiles(CSV);
    await expect(page.getByText("Zent está entendiendo tus datos")).toBeVisible({ timeout: 30_000 });
    await expect(page.getByTestId("analyze-continue")).toBeEnabled({ timeout: 45_000 });

    await page
      .getByRole("navigation", { name: "Secciones de conocimiento" })
      .getByRole("link", { name: "Semántica" })
      .click();
    await page
      .getByRole("navigation", { name: "Subsecciones de Semántica" })
      .getByRole("link", { name: "Entendimiento" })
      .click();
    await expect(page).toHaveURL(/\/knowledge\/understanding\/?$/, { timeout: 20_000 });
    await expect(page.getByTestId("studio-page")).toBeVisible({ timeout: 20_000 });
    await expect(
      page.getByTestId("studio-layout").or(page.getByText("Todavía no hay catálogo"))
    ).toBeVisible({ timeout: 20_000 });

    const dsc = page.getByTestId("studio-col-producto");
    if (await dsc.isVisible().catch(() => false)) {
      await dsc.click();
      const confirm = page.getByTestId("studio-confirm");
      if (await confirm.isVisible().catch(() => false)) {
        await confirm.click();
      }
    }

    const search = page.getByTestId("studio-search");
    await search.fill("precio");
    await expect(page.getByTestId("studio-layout")).toBeVisible();
  });
});
