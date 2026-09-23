import { expect, test } from "@playwright/test";
import {
  AGENT_NAME,
  cleanupSmokeAgent,
  cleanupSmokeKeys,
  expectNoA11yViolations,
  loginAsTenant,
} from "./fixtures";

test.describe("Customer portal — flujo smoke", () => {
  test("login → dashboard → agente → knowledge → playground → eval → deploy → keys → logout", async ({
    page,
    request,
  }) => {
    page.on("response", async (resp) => {
      if (resp.status() === 429 && resp.url().includes("/api/v1")) {
        console.log("429 URL:", resp.url().replace("http://127.0.0.1:8090", ""));
        console.log("429 BODY:", (await resp.text()).slice(0, 220));
      }
    });
    await cleanupSmokeAgent(request);
    await cleanupSmokeKeys(request);

    // Login
    await loginAsTenant(page);
    await expect(page.getByRole("heading", { name: "Panel general" })).toBeVisible();
    const dashboardKnowledge = page.getByTestId("knowledge-pillar-links");
    await expect(dashboardKnowledge.getByRole("link", { name: "Resumen" })).toHaveAttribute(
      "href",
      "/knowledge"
    );
    await expect(dashboardKnowledge.getByRole("link", { name: "Fuentes" })).toHaveAttribute(
      "href",
      "/knowledge/sources"
    );
    await expect(dashboardKnowledge.getByRole("link", { name: "Aprendizaje" })).toHaveAttribute(
      "href",
      "/knowledge/learning"
    );
    await expectNoA11yViolations(page);

    // Crear agente (UI)
    await page.goto("/agents");
    await expect(page.getByRole("heading", { name: "Agentes" })).toBeVisible();
    await expect(page.getByTestId("knowledge-pillar-links")).toHaveCount(0);
    await page.getByRole("link", { name: "Crear agente" }).first().click();
    await page.getByLabel("Nombre").fill(AGENT_NAME);
    await page.getByRole("button", { name: "Crear agente" }).click();
    await expect(page).toHaveURL(/\/agents\/[0-9a-f-]{36}(?:\?.*)?$/);
    const agentUrl = page.url();
    const agentId = agentUrl.match(/\/agents\/([^/?]+)/)?.[1];
    expect(agentId).toBeTruthy();
    await expect(page.getByRole("heading", { name: "Probar" })).toBeVisible();
    await page.getByLabel("Propósito", { exact: true }).fill("Responder dudas internas");
    const sourceBox = page.getByRole("checkbox", { name: /docs/i }).first();
    if (await sourceBox.count()) {
      await sourceBox.check();
    }
    await page.getByRole("button", { name: "Guardar" }).click();
    await expect(page.getByText("Cambios guardados.")).toBeVisible();
    await page.getByPlaceholder("Pregunta al agente…").fill("¿Cuál es la política?");
    await page.getByRole("button", { name: "Probar" }).click();
    await expect(page.getByPlaceholder("Pregunta al agente…")).toBeEnabled({ timeout: 25_000 });
    await page.getByRole("button", { name: "Volver" }).click();
    await expect(page.getByRole("heading", { name: "Agentes" })).toBeVisible();
    await expect(page.getByText(AGENT_NAME)).toBeVisible();
    await page
      .locator(".panel", { hasText: AGENT_NAME })
      .getByRole("link", { name: "Editar" })
      .click();
    await expect(page).toHaveURL(new RegExp(`/agents/${agentId}`));
    await expect(page.getByLabel("Nombre")).toHaveValue(AGENT_NAME);

    // Knowledge
    await page.goto("/knowledge");
    await expect(page.getByRole("heading", { name: "Resumen", exact: true })).toBeVisible();
    const knowledgeNav = page.getByRole("navigation", { name: "Secciones de conocimiento" });
    await expect(knowledgeNav.getByRole("link", { name: "Resumen" })).toBeVisible();
    await expect(knowledgeNav.getByRole("link", { name: "Fuentes" })).toBeVisible();
    await expect(knowledgeNav.getByRole("link", { name: "Aprendizaje" })).toBeVisible();
    await expect(knowledgeNav.getByRole("button", { name: "Avanzado" })).toBeVisible();
    await expect(knowledgeNav.getByRole("link")).toHaveCount(3);
    await page.goto("/knowledge/sources");
    await expect(page.getByRole("heading", { name: "Fuentes", exact: true })).toBeVisible();
    await expect(knowledgeNav.getByRole("link", { name: "Fuentes" })).toBeVisible();

    // Playground: elige el agente recién creado (o conocimiento si no hay)
    await page.goto("/chat");
    await expect(page.getByRole("heading", { name: "Playground" })).toBeVisible();
    await expect(page.getByTestId("playground-target-bar")).toBeVisible();
    await expect(page.getByLabel("Qué probar")).toBeVisible();
    const composer = page.getByRole("textbox", { name: "Tu pregunta" });
    await composer.fill("¿Qué es Zent?");
    await composer.press("Enter");
    await page.waitForTimeout(4000);
    await expect(page.getByRole("textbox", { name: "Tu pregunta" })).toBeVisible();

    // Evaluation / Calidad
    await page.goto("/ai-quality");
    await expect(page.getByRole("heading", { name: "Calidad de IA" })).toBeVisible();
    await page.goto("/evaluation");
    await expect(page.getByRole("heading", { name: "Evaluation" })).toBeVisible();

    // Publicar: versión → lista → producción
    await page.goto(`/agents/${agentId}/builder?tab=versions`);
    await page.getByRole("button", { name: "Crear versión" }).click();
    await expect(page.getByText(/Snapshot creado/)).toBeVisible({ timeout: 20000 });
    await page.getByRole("button", { name: "Marcar como lista" }).first().click();
    await expect(page.getByText(/Versión promovida/)).toBeVisible({ timeout: 20000 });
    await page.goto(`/agents/${agentId}/builder?tab=deployments`);
    await expect(page.getByRole("combobox", { name: "Versión a publicar" })).toContainText("v1 · ready", {
      timeout: 20000,
    });
    await expect(page.getByRole("combobox", { name: "Entorno" })).toContainText("production", {
      timeout: 20000,
    });
    await page.getByRole("button", { name: "Publicar en producción" }).click();
    await expect(page.getByText(/desplegada en production/)).toBeVisible({ timeout: 20000 });
    await page.goto("/deployments");
    await expect(page.getByRole("heading", { name: "Despliegues" })).toBeVisible();

    // API Keys: crear y revelar una vez
    await page.goto("/keys");
    await page.getByRole("button", { name: "Nueva clave" }).click();
    await page.getByPlaceholder(/backend-prod/).fill("e2e-smoke-key");
    await page.getByRole("button", { name: "Crear" }).click();
    const keyInput = page.getByLabel("Nueva clave");
    await expect(keyInput).toHaveValue(/^zent_sk_/, { timeout: 20000 });
    await page.getByRole("button", { name: "Ocultar clave" }).click();
    await expect(keyInput).not.toHaveValue(/^zent_sk_/);

    // Logout
    await page.getByRole("button", { name: "Cuenta" }).click();
    await page.getByRole("menuitem", { name: "Cerrar sesión" }).click();
    await expect(page).toHaveURL(/\/login$/);
  });
});