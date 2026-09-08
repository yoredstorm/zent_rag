import path from "path";
import { fileURLToPath } from "url";
import { expect, test } from "@playwright/test";

const CSV = path.join(path.dirname(fileURLToPath(import.meta.url)), "fixtures", "productos.csv");

test.describe("Data onboarding wizard — org nueva CSV", () => {
  test("signup → dashboard empty → CSV → review → pregunta → ready", async ({ page }) => {
    const stamp = Date.now();
    const email = `e2e-onb-${stamp}@example.com`;
    const password = "Onboard123!";

    await page.goto("/signup");
    await page.getByLabel("Nombre de empresa").fill(`E2E Onboarding ${stamp}`);
    await page.getByLabel("Email").fill(email);
    await page.getByLabel("Contraseña", { exact: true }).fill(password);
    await page.getByLabel("Confirmar contraseña").fill(password);
    await page.getByRole("button", { name: "Empezar trial" }).click();

    await expect(page).toHaveURL(/\/$/, { timeout: 30_000 });
    const keyDialog = page.getByRole("dialog", { name: "Tu API key" });
    await expect(keyDialog).toBeVisible({ timeout: 20_000 });
    await page.getByRole("button", { name: "Ya la guardé" }).click();
    await expect(keyDialog).toBeHidden();

    await expect(page.getByRole("heading", { name: "Bienvenido a Zent" })).toBeVisible({
      timeout: 20_000,
    });
    await page.getByRole("link", { name: "Conectar mis datos" }).click();
    await expect(page).toHaveURL(/\/knowledge\/add/);

    await page.getByTestId("source-kind-spreadsheets").click();
    await expect(page.getByText("Sube tus archivos")).toBeVisible();
    await page.getByTestId("onboarding-file").setInputFiles(CSV);

    await expect(page.getByText("Zent está entendiendo tus datos")).toBeVisible({
      timeout: 30_000,
    });
    await expect(page.getByTestId("analyze-continue")).toBeEnabled({ timeout: 45_000 });
    await page.getByTestId("analyze-continue").click();

    await expect(page.getByRole("heading", { name: "Qué entendió Zent" })).toBeVisible({
      timeout: 20_000,
    });
    const confirm = page.getByTestId("review-confirm").first();
    if (await confirm.isVisible().catch(() => false)) {
      await confirm.click();
    }
    await page.getByTestId("goto-questions").click();

    await expect(page.getByRole("heading", { name: "Prueba Zent" })).toBeVisible();
    const question = page.getByTestId("generated-question").first();
    await expect(question).toBeVisible();
    await question.click();
    await expect(page.getByText(/Pregunta entendida|Pendiente de indexar/)).toBeVisible({
      timeout: 30_000,
    });

    await page.getByTestId("finish-wizard").click();
    await expect(page.getByTestId("ready-heading")).toBeVisible({ timeout: 20_000 });
  });
});
