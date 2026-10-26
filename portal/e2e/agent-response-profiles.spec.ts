import { expect, test } from "@playwright/test";
import { apiAsTenant, loginAsTenant, suppressProductTour } from "./fixtures";

test.describe("Agent Studio · perfiles de respuesta P14", () => {
  test("selecciona un preset, guarda y lo conserva al recargar", async ({
    page,
    request,
  }) => {
    await suppressProductTour(page);
    const created = await apiAsTenant(request, "/agents", {
      method: "POST",
      body: JSON.stringify({
        name: `E2E perfil ${Date.now()}`,
        tools: [],
        config: { response_profile: { preset: "balanced" } },
      }),
    });
    expect(created.ok()).toBeTruthy();
    const agent = (await created.json()) as { id: string };

    try {
      await loginAsTenant(page);
      await page.goto(`/agents/${agent.id}?panel=advanced&tab=response`);
      await expect(page.getByTestId("agent-group-response-detail")).toBeVisible({
        timeout: 20_000,
      });

      // El catálogo viene del backend: los ocho presets están presentes.
      for (const id of [
        "balanced",
        "precise",
        "clear_didactic",
        "technical_detailed",
        "executive",
        "concise",
        "analytical",
        "evidence_first",
      ]) {
        await expect(page.locator(`#response-preset-${id}`)).toBeVisible();
      }

      await page.locator("#response-preset-concise").click();
      await expect(page.locator("#response-preset-concise")).toHaveAttribute(
        "aria-pressed",
        "true",
      );
      // Elegir Conciso no deja campos exclusivos de Analítico.
      await expect(page.locator("#response-preset-analytical")).toHaveAttribute(
        "aria-pressed",
        "false",
      );

      await page.getByRole("button", { name: "Guardar" }).click();
      await expect(page.getByText(/Cambios guardados/)).toBeVisible({
        timeout: 20_000,
      });

      const saved = await apiAsTenant(request, `/agents/${agent.id}`);
      expect(saved.ok()).toBeTruthy();
      const body = (await saved.json()) as {
        config: { response_profile: { profile_id: string; structure_policy: string } };
      };
      expect(body.config.response_profile.profile_id).toBe("concise");
      expect(body.config.response_profile.structure_policy).toBe("answer_only");

      await page.reload();
      await expect(page.getByTestId("agent-group-response-detail")).toBeVisible({
        timeout: 20_000,
      });
      await expect(page.locator("#response-preset-concise")).toHaveAttribute(
        "aria-pressed",
        "true",
      );
      await expect(
        page.getByTestId("agent-group-response").getByText("Personalizado", { exact: true }),
      ).toHaveCount(0);
    } finally {
      await apiAsTenant(request, `/agents/${agent.id}`, { method: "DELETE" });
    }
  });
});
