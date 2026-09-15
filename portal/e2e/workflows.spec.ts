import { expect, test } from "@playwright/test";
import { AGENT_NAME, apiAsTenant, cleanupSmokeAgent, loginAsTenant, suppressProductTour } from "./fixtures";

test.describe("Workflow Studio", () => {
  test.beforeAll(async ({ request }) => {
    // En CI puede no haber agentes: garantiza uno para el select del nodo llm.
    await apiAsTenant(request, "/agents", {
      method: "POST",
      body: JSON.stringify({ name: AGENT_NAME, description: "E2E workflow studio" }),
    });
  });

  test.afterAll(async ({ request }) => {
    await cleanupSmokeAgent(request);
  });

  test("crear, armar el canvas, probar con el agente y abrir API/Avanzado", async ({ page }) => {
    await suppressProductTour(page);
    await loginAsTenant(page);
    await page.goto("/workflows");
    await expect(page.getByRole("heading", { name: "Workflow Automation" })).toBeVisible({ timeout: 20_000 });

    // La lista ya no trae editor: modo manual → estudio.
    await page.getByTestId("wf-new-modes").click();
    await expect(page).toHaveURL(/\/workflows\/new/, { timeout: 10_000 });
    await page.getByTestId("wf-mode-manual").click();
    await page.getByTestId("wf-new-name").fill("E2E Studio Flow");
    await page.getByTestId("wf-create").click();

    // Estudio inmersivo: rail + lienzo + dock de prueba, sin pestañas.
    await expect(page.getByTestId("workflow-canvas-editor")).toBeVisible({ timeout: 20_000 });
    await expect(page.getByTestId("wf-node-library")).toBeVisible();
    await expect(page.getByTestId("wf-test-panel")).toBeVisible();
    await expect(async () => {
      const n = await page.getByTestId("wf-canvas-node").count();
      expect(n).toBeGreaterThanOrEqual(2);
    }).toPass({ timeout: 15_000 });

    // Agregar "Preguntar a un agente": se auto-conecta y abre su inspector.
    await page.getByTestId("wf-add-llm").click();
    await expect(async () => {
      const n = await page.getByTestId("wf-canvas-node").count();
      expect(n).toBeGreaterThanOrEqual(3);
    }).toPass({ timeout: 10_000 });
    await expect(page.getByTestId("wf-node-config")).toBeVisible({ timeout: 10_000 });

    // El agente es obligatorio: se elige del select de negocio o se ofrece crear uno.
    const agentSelect = page.getByTestId("wf-param-agent_id");
    await expect(agentSelect).toBeVisible();
    const options = await agentSelect.locator("option").count();
    if (options > 1) {
      await agentSelect.selectOption({ index: 1 });
      await expect(page.getByTestId("wf-agent-required")).toHaveCount(0);
    } else {
      await expect(page.getByTestId("wf-agent-cta")).toBeVisible();
    }

    // El prompt por defecto usa el payload del trigger.
    await expect(page.getByTestId("wf-param-prompt")).toHaveValue("{{trigger.message}}");

    // Guardar desde la cabecera del estudio.
    await expect(page.getByText("Cambios sin guardar")).toBeVisible({ timeout: 10_000 });
    await page.getByTestId("wf-save").click();
    await expect(page.getByText(/Guardado/).first()).toBeVisible({ timeout: 15_000 });

    // Probar: la pregunta llega como {{trigger.message}} y la respuesta es texto.
    await page.getByTestId("wf-test-payload").fill("quien es el gerente");
    await expect(page.getByTestId("wf-payload-wrapped")).toBeVisible();
    await page.getByTestId("wf-test").click();

    await expect(page.getByTestId("wf-run-inspector")).toBeVisible({ timeout: 30_000 });
    const answer = page.getByTestId("wf-chat-answer");
    const system = page.getByTestId("wf-chat-system");
    await expect(async () => {
      expect((await answer.count()) + (await system.count())).toBeGreaterThan(0);
    }).toPass({ timeout: 15_000 });
    // Ya no se responde con el JSON crudo del dry-run.
    await expect(page.getByText(/^Dry-run: simulated$/)).toHaveCount(0);

    // Un paso del run salta al nodo en el lienzo.
    await page.getByTestId("wf-step-jump").first().click();
    await expect(page.getByTestId("wf-node-config")).toBeVisible({ timeout: 10_000 });

    // API: drawer con endpoint, header del secret y contrato Android.
    await page.getByTestId("wf-open-api").click();
    await expect(page.getByTestId("wf-drawer-api")).toBeVisible({ timeout: 10_000 });
    await expect(page.getByTestId("wf-api-inactive")).toBeVisible();
    await expect(page.getByText(/api\/v1\/public\/workflows/).first()).toBeVisible();
    await expect(page.getByText(/X-Zent-Workflow-Secret/).first()).toBeVisible();
    await expect(page.getByTestId("wf-android-contract")).toBeVisible();
    await page.getByTestId("wf-drawer-api").getByRole("button", { name: "Cerrar", exact: true }).click();
    await expect(page.getByTestId("wf-drawer-api")).toHaveCount(0);

    // Avanzado: drawer de versiones, snapshot al historial.
    await page.getByTestId("wf-open-advanced").click();
    await expect(page.getByTestId("wf-drawer-advanced")).toBeVisible({ timeout: 10_000 });
    await expect(page.getByTestId("wf-advanced-panel")).toBeVisible({ timeout: 10_000 });
    await page.getByTestId("wf-snapshot").click();
    await expect(page.getByTestId("wf-version-row").first()).toBeVisible({ timeout: 15_000 });
  });

  test("instala plantilla stock y abre su estudio", async ({ page }) => {
    await suppressProductTour(page);
    await loginAsTenant(page);
    await page.goto("/workflows");
    await expect(page.getByRole("heading", { name: "Workflow Automation" })).toBeVisible({ timeout: 20_000 });

    const install = page.getByTestId("wf-install-low-stock-alert");
    if (await install.isVisible()) {
      await install.click();
      await expect(page).toHaveURL(/\/workflows\/[0-9a-f-]{36}/, { timeout: 20_000 });
      await expect(page.getByTestId("wf-name")).toHaveValue("Alerta de stock bajo", { timeout: 15_000 });
      await expect(page.getByTestId("workflow-canvas-editor")).toBeVisible();
    }
  });
});
