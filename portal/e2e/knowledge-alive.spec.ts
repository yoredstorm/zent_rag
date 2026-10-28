import fs from "fs";
import path from "path";
import { expect, test } from "@playwright/test";
import { expectNoA11yViolations } from "./fixtures";

/**
 * P18-01/P18-02 smoke visual: cuatro pestañas, sin segunda barra y wizard
 * de incorporación en desktop y móvil. No escribe conocimiento.
 */
test("P18 knowledge alive: navegación y wizard en desktop/móvil", async ({
  page,
  request,
}) => {
  const stamp = Date.now();
  const signup = await request.post("/api/v1/auth/signup", {
    data: {
      company_name: `P18 UX ${stamp}`,
      email: `p18-ux-${stamp}@example.com`,
      password: "P18-ux-password-123",
    },
  });
  expect(signup.ok()).toBeTruthy();
  const session = (await signup.json()) as {
    access_token: string;
    organization_id: string;
    company_name: string;
    email: string;
  };
  const start = await request.post("/api/v1/onboarding/start-mode", {
    headers: {
      Authorization: `Bearer ${session.access_token}`,
      "X-Organization-Id": session.organization_id,
      "Idempotency-Key": crypto.randomUUID(),
      "Content-Type": "application/json",
    },
    data: { mode: "blank" },
  });
  expect(start.ok()).toBeTruthy();
  const workspace = (await start.json()) as { workspace_id: string; kind: string };

  await page.addInitScript(
    ({ token, organizationId, companyName, email, workspaceId, workspaceKind }) => {
      sessionStorage.setItem("rag_portal_token", token);
      localStorage.setItem("rag_portal_org", organizationId);
      localStorage.setItem("rag_portal_company", companyName);
      localStorage.setItem("rag_portal_email", email);
      localStorage.setItem("rag_portal_workspace", workspaceId);
      localStorage.setItem("rag_portal_workspace_kind", workspaceKind);
      localStorage.setItem("zent_product_tour_v2", JSON.stringify({ status: "completed" }));
    },
    {
      token: session.access_token,
      organizationId: session.organization_id,
      companyName: session.company_name,
      email: session.email,
      workspaceId: workspace.workspace_id,
      workspaceKind: workspace.kind,
    },
  );

  const outDir = path.join(process.cwd(), "..", "artifacts", "certification", "p18");
  fs.mkdirSync(outDir, { recursive: true });

  for (const viewport of [
    { name: "1366", width: 1366, height: 768 },
    { name: "390", width: 390, height: 844 },
  ]) {
    await page.setViewportSize({ width: viewport.width, height: viewport.height });
    await page.goto("/knowledge", { waitUntil: "domcontentloaded" });
    const nav = page.getByRole("navigation", { name: "Secciones de conocimiento" });
    await expect(nav).toBeVisible({ timeout: 30_000 });
    await expect(page.getByTestId("knowledge-hero")).toBeVisible({ timeout: 30_000 });
    await expect(page.getByTestId("knowledge-hero")).not.toHaveAttribute(
      "aria-busy",
      "true",
    );
    await expect(page.getByRole("heading", { level: 1 })).toContainText(
      /información|conocimiento/i,
    );
    await expect(nav.getByRole("link", { name: "Resumen" })).toBeVisible();
    await expect(nav.getByRole("link", { name: "Fuentes" })).toBeVisible();
    await expect(nav.getByRole("link", { name: "Preguntar" })).toBeVisible();
    await expect(nav.getByRole("link", { name: "Mejorar" })).toBeVisible();
    await expect(nav.getByRole("button", { name: "Herramientas avanzadas" })).toBeVisible();
    await expect(nav.getByRole("link")).toHaveCount(4);
    const bodyWidth = await page.evaluate(() => document.body.scrollWidth);
    expect(bodyWidth, `${viewport.name}px sin overflow horizontal`).toBeLessThanOrEqual(
      viewport.width + 1,
    );
    await expectNoA11yViolations(page);
    await page.screenshot({
      path: path.join(outDir, `knowledge-home-${viewport.name}.png`),
      fullPage: true,
    });

    await nav.getByRole("link", { name: "Fuentes" }).click();
    await expect(page.getByRole("heading", { name: "Fuentes", exact: true })).toBeVisible({
      timeout: 30_000,
    });
    await page.getByRole("button", { name: "Añadir información" }).click();
    await expect(page.getByTestId("knowledge-import-wizard")).toBeVisible({
      timeout: 30_000,
    });
    await expect(page.getByTestId("wizard-choose")).toContainText("Subir documentos");
    await expect(page.getByTestId("wizard-choose")).toContainText("Conectar un sistema");
    await page.screenshot({
      path: path.join(outDir, `knowledge-import-${viewport.name}.png`),
      fullPage: true,
    });
    await page.getByRole("button", { name: /Subir documentos/ }).click();
    await expect(page.getByTestId("wizard-source-files")).toBeVisible();
    await page.screenshot({
      path: path.join(outDir, `knowledge-import-files-${viewport.name}.png`),
      fullPage: true,
    });
  }
});
