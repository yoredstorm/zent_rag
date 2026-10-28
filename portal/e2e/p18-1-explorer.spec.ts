import fs from "fs";
import path from "path";
import { expect, test } from "@playwright/test";
import { expectNoA11yViolations } from "./fixtures";

/**
 * P18.1-08/09 — Explorador documental real.
 * Sube una política pequeña, espera el indexado y comprueba que el Explorador
 * muestra el documento, su resumen y los límites de certeza sin inventar temas.
 */
test("P18.1 explorador documental: fuente real, resumen y evidencia", async ({
  page,
  request,
}) => {
  const stamp = Date.now();
  const signup = await request.post("/api/v1/auth/signup", {
    data: {
      company_name: `P181 Explorer ${stamp}`,
      email: `p181-explorer-${stamp}@example.com`,
      password: "P181-explorer-password-123",
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

  const corpusResponse = await request.post("/api/v1/knowledge/workspaces", {
    headers,
    data: { name: "Principal" },
  });
  expect(corpusResponse.ok()).toBeTruthy();
  const corpus = (await corpusResponse.json()) as { corpus: { id: string } };

  const upload = await request.post(
    `/api/v1/sources/files/upload?corpus_id=${corpus.corpus.id}`,
    {
      headers,
      multipart: {
        file: {
          name: "politica-gastos.txt",
          mimeType: "text/plain",
          buffer: Buffer.from(
            "Política de aprobación de gastos\n" +
              "El empleado debe solicitar aprobación antes de comprometer el gasto.\n" +
              "El responsable autorizará el monto y dejará evidencia de la decisión.\n" +
              "El procedimiento es obligatorio para todos los empleados.\n",
          ),
        },
      },
    },
  );
  expect(upload.ok()).toBeTruthy();

  let ready = false;
  for (let attempt = 0; attempt < 60; attempt += 1) {
    const detail = await request.get(
      `/api/v1/knowledge/workspaces/${corpus.corpus.id}`,
      { headers },
    );
    if (detail.ok()) {
      const payload = (await detail.json()) as {
        sources: { status: string }[];
      };
      if (payload.sources.some((source) => source.status === "indexed")) {
        ready = true;
        break;
      }
    }
    await page.waitForTimeout(1000);
  }
  expect(ready).toBeTruthy();

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

  const outDir = path.join(process.cwd(), "..", "artifacts", "certification", "p18-1");
  fs.mkdirSync(outDir, { recursive: true });
  for (const viewport of [
    { name: "1366", width: 1366, height: 768 },
    { name: "390", width: 390, height: 844 },
  ]) {
    await page.setViewportSize({ width: viewport.width, height: viewport.height });
    await page.goto("/knowledge/explorer", { waitUntil: "domcontentloaded" });
    await expect(
      page.getByRole("heading", { name: "Qué encontramos en tus documentos" }),
    ).toBeVisible({ timeout: 30_000 });
    await expect(page.getByTestId("knowledge-document-insight")).toBeVisible({
      timeout: 30_000,
    });
    await expect(page.getByText("politica-gastos.txt").first()).toBeVisible();
    await expect(page.getByText(/Documento de naturaleza/)).toBeVisible();
    await expect(page.getByText(/hallazgos visibles/).first()).toBeVisible();
    await expect(
      page.getByText(/clasificación de género es provisional/i),
    ).toBeVisible();
    const bodyWidth = await page.evaluate(() => document.body.scrollWidth);
    expect(bodyWidth, `${viewport.name}px sin overflow`).toBeLessThanOrEqual(
      viewport.width + 1,
    );
    await expectNoA11yViolations(page);
    await page.screenshot({
      path: path.join(outDir, `explorer-document-${viewport.name}.png`),
      fullPage: true,
    });
  }
});
