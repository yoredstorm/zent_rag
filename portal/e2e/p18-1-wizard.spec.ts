import { expect, test } from "@playwright/test";

/**
 * P18.1-03 — Wizard durable con recarga y resultado parcial.
 * Sube 3 archivos, uno duplicado; recarga con session_id y comprueba que el
 * estado durable reconstruye las fuentes sin decir "0 archivos".
 */
test("P18.1 wizard: lote parcial, recarga y reapertura durable", async ({
  page,
  request,
}) => {
  const stamp = Date.now();
  const signup = await request.post("/api/v1/auth/signup", {
    data: {
      company_name: `P181 Wizard ${stamp}`,
      email: `p181-wizard-${stamp}@example.com`,
      password: "P181-wizard-password-123",
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
  const headers = {
    Authorization: `Bearer ${session.access_token}`,
    "X-Organization-Id": session.organization_id,
    "X-Workspace-Id": workspace.workspace_id,
    "Idempotency-Key": crypto.randomUUID(),
  };

  // Fuente preexistente con el mismo nombre: el tercer archivo del lote será
  // un duplicado real, no una simulación de error.
  const duplicate = await request.post("/api/v1/sources/files/upload-batch", {
    headers,
    multipart: {
      files: {
        name: "duplicado.txt",
        mimeType: "text/plain",
        buffer: Buffer.from("Contenido original del duplicado.\n"),
      },
    },
  });
  expect(duplicate.ok()).toBeTruthy();

  await page.addInitScript(
    ({ token, organizationId, companyName, email, workspaceId, workspaceKind }) => {
      sessionStorage.setItem("rag_portal_token", token);
      localStorage.setItem("rag_portal_org", organizationId);
      localStorage.setItem("rag_portal_company", companyName);
      localStorage.setItem("rag_portal_email", email);
      localStorage.setItem("rag_portal_workspace", workspaceId);
      localStorage.setItem("rag_portal_workspace_kind", workspaceKind);
      localStorage.setItem(
        "zent_product_tour_v2",
        JSON.stringify({ status: "completed" }),
      );
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

  await page.goto("/knowledge/sources?new=1", { waitUntil: "domcontentloaded" });
  await page.getByRole("button", { name: /Subir documentos/ }).click();
  const input = page.getByTestId("wizard-source-files");
  await input.setInputFiles([
    {
      name: "uno.txt",
      mimeType: "text/plain",
      buffer: Buffer.from("Política uno: el empleado debe aprobar el gasto.\n"),
    },
    {
      name: "dos.txt",
      mimeType: "text/plain",
      buffer: Buffer.from("Política dos: el responsable autoriza el monto.\n"),
    },
    {
      name: "duplicado.txt",
      mimeType: "text/plain",
      buffer: Buffer.from("Contenido distinto con el mismo nombre.\n"),
    },
  ]);
  await page.getByRole("button", { name: "Incorporar 3 archivos" }).click();

  await expect(page.getByTestId("wizard-check")).toBeVisible({ timeout: 90_000 });
  await expect(page.getByTestId("wizard-session-check")).toBeVisible({
    timeout: 90_000,
  });
  await expect(page.getByText("Ya existe")).toBeVisible({ timeout: 30_000 });
  await expect(page.getByText(/2 archivos recibidos/)).toBeVisible();

  const sessionUrl = page.url();
  expect(sessionUrl).toContain("session_id=");
  await page.reload({ waitUntil: "domcontentloaded" });
  await expect(page.getByTestId("knowledge-import-wizard")).toBeVisible({
    timeout: 30_000,
  });
  await expect(page.getByTestId("wizard-session-check")).toBeVisible({
    timeout: 90_000,
  });
  await expect(page.getByText(/de 2 fuentes listas/).first()).toBeVisible({
    timeout: 30_000,
  });
  await expect(page.getByText("uno.txt").first()).toBeVisible();
  await expect(page.getByText("dos.txt").first()).toBeVisible();
  await expect(page.getByText(/Todavía no hay archivos en este recorrido/)).toHaveCount(0);

  // Un lote nuevo no reutiliza la sesión sellada: vuelve a elegir archivos y
  // limpia el estado de comprobación.
  await page.getByRole("button", { name: "Añadir más archivos" }).click();
  await expect(page.getByTestId("wizard-source-files")).toBeVisible();
  await expect(page.getByTestId("wizard-session-check")).toHaveCount(0);
});
