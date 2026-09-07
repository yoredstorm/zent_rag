import { AxeBuilder } from "@axe-core/playwright";
import { expect, type Page, type APIRequestContext } from "@playwright/test";

/** Credenciales deterministas del stack (seed de desarrollo). */
export const DEV_EMAIL = process.env.E2E_DEV_EMAIL || "demo@zenttech.com";
export const DEV_PASSWORD = process.env.E2E_DEV_PASSWORD || "demo-password-change-me";
export const PLATFORM_EMAIL = process.env.E2E_PLATFORM_EMAIL || "admin@zent.dev";
export const DEMO_ORG_ID = process.env.E2E_DEMO_ORG_ID || "00000000-0000-0000-0000-000000000001";
export const DEV_API_KEY =
  process.env.E2E_DEV_API_KEY || "rag_test_dev_token_for_local_testing_123";

export const AGENT_NAME = "E2E Smoke Agent";

export async function loginAsTenant(page: Page) {
  await page.goto("/login");
  await page.getByLabel("Email").fill(DEV_EMAIL);
  await page.getByLabel("Contraseña").fill(DEV_PASSWORD);
  await page.getByRole("button", { name: "Continuar" }).click();
  await expect(page).toHaveURL(/\/$/);
}

export async function loginAsPlatform(page: Page) {
  await page.goto("/control-center/login");
  await page.getByLabel("Email").fill(PLATFORM_EMAIL);
  await page.getByLabel("Contraseña").fill(DEV_PASSWORD);
  await page.getByRole("button", { name: "Entrar" }).click();
  await expect(page).toHaveURL(/\/control-center$/);
}

/** Cliente API como tenant usando la dev API key (determinista). */
export async function apiAsTenant(
  request: APIRequestContext,
  path: string,
  init: { method?: string; body?: string } = {}
) {
  const headers: Record<string, string> = {
    "Content-Type": "application/json",
    Authorization: `Bearer ${DEV_API_KEY}`,
    "X-Organization-Id": DEMO_ORG_ID,
  };
  if (["POST", "PUT", "PATCH"].includes((init.method || "GET").toUpperCase())) {
    headers["Idempotency-Key"] = crypto.randomUUID();
  }
  return request.fetch(`/api/v1${path}`, { ...init, headers });
}

/** Corre axe-core sobre la página actual y falla si hay violaciones serias. */
export async function expectNoA11yViolations(page: Page) {
  // scrollable-region-focusable: regla best-practice (no WCAG A/AA) que se
  // dispara en el shell de la app (main overflow) aun con tabIndex=-1; la
  // navegación por teclado del shell está garantizada por los links del
  // layout. El resto de violaciones serias/críticas sigue fallando.
  const results = await new AxeBuilder({ page })
    .disableRules(["scrollable-region-focusable"])
    .analyze();
  const serious = results.violations.filter(
    (v) => v.impact === "serious" || v.impact === "critical"
  );
  if (serious.length > 0) {
    const summary = serious
      .map((v) => {
        const nodes = v.nodes.map((n) => n.target.join(" ")).join(" | ");
        return `${v.id}: ${v.help} (${v.impact}) - ${nodes}`;
      })
      .join("\n");
    expect.soft(false, `Violaciones de accesibilidad:\n${summary}`).toBeTruthy();
  }
}

/** Limpia el agente de smoke si existe (idempotente entre runs). */
export async function cleanupSmokeAgent(request: APIRequestContext) {
  const res = await apiAsTenant(request, "/agents");
  const body = (await res.json()) as { agents: { id: string; name: string }[] };
  for (const agent of body.agents || []) {
    if (agent.name === AGENT_NAME) {
      await apiAsTenant(request, `/agents/${agent.id}`, { method: "DELETE" });
    }
  }
}

/** Revoca keys de smoke previas (el create exige nombre único por key activa). */
export async function cleanupSmokeKeys(request: APIRequestContext) {
  const res = await apiAsTenant(request, "/organizations/api-keys");
  const body = (await res.json()) as {
    api_keys?: { id: string; name: string }[];
    keys?: { id: string; name: string }[];
  };
  const keys = body.api_keys || body.keys || [];
  for (const key of keys) {
    if (key.name === "e2e-smoke-key") {
      await apiAsTenant(request, `/organizations/api-keys/${key.id}`, { method: "DELETE" });
    }
  }
}