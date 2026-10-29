import fs from "fs";
import path from "path";
import { expect, test } from "@playwright/test";
import { expectNoA11yViolations } from "./fixtures";

/**
 * P18.2 — Explorador documental vs vista técnica.
 * Requiere API + worker reales. Se omite en CI sin ingesta.
 */
test.skip(
  process.env.P18_2_E2E_INGEST !== "1",
  "Requiere worker de ingesta; CI E2E no lo levanta.",
);

test("P18.2 separa documento de listado técnico y respeta 390/1366", async ({
  page,
  request,
}) => {
  const stamp = Date.now();
  const signup = await request.post("/api/v1/auth/signup", {
    data: {
      company_name: `P182 Explorer ${stamp}`,
      email: `p182-explorer-${stamp}@example.com`,
      password: "P182-explorer-password-123",
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
  const corpus = (await corpusResponse.json()) as { corpus: { id: string } };

  const upload = await request.post(
    `/api/v1/sources/files/upload?corpus_id=${corpus.corpus.id}`,
    {
      headers,
      multipart: {
        file: {
          name: "manual-p18-2.txt",
          mimeType: "text/plain",
          buffer: Buffer.from(
            "Manual de registro sintético\n" +
              "Campo Fare Basis | posición 12 | longitud 8 | máscara AAAAAAAA\n" +
              "Campo Currency | posición 20 | longitud 3 | formato ISO 4217\n" +
              "El registro debe validar la máscara antes de publicar.\n",
          ),
        },
      },
    },
  );
  expect(upload.ok()).toBeTruthy();
  const source = (await upload.json()) as { id: string; session_id?: string };

  for (let attempt = 0; attempt < 60; attempt += 1) {
    const detail = await request.get(
      `/api/v1/knowledge/workspaces/${corpus.corpus.id}`,
      { headers },
    );
    if (detail.ok()) {
      const payload = (await detail.json()) as {
        sources: { id: string; status: string }[];
      };
      if (
        payload.sources.some(
          (item) => item.id === source.id && item.status === "indexed",
        )
      ) {
        break;
      }
    }
    await page.waitForTimeout(1000);
  }

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

  const outDir = path.join(process.cwd(), "..", "artifacts", "certification", "p18-2");
  fs.mkdirSync(outDir, { recursive: true });

  for (const viewport of [
    { name: "1366", width: 1366, height: 768 },
    { name: "390", width: 390, height: 844 },
  ]) {
    await page.setViewportSize({ width: viewport.width, height: viewport.height });
    await page.goto(
      `/knowledge/explorer?source=${source.id}`,
      { waitUntil: "domcontentloaded" },
    );
    await expect(page.getByTestId("knowledge-document-insight")).toBeVisible({
      timeout: 30_000,
    });
    await expect(
      page.getByRole("heading", { name: "Qué contiene este documento" }),
    ).toBeVisible();
    await expect(page.getByTestId("technical-view-banner")).toHaveCount(0);
    await expect(
      page.getByRole("link", { name: "Preguntar sobre este documento" }),
    ).toBeVisible();
    const bodyWidth = await page.evaluate(() => document.body.scrollWidth);
    expect(bodyWidth, `${viewport.name}px sin overflow`).toBeLessThanOrEqual(
      viewport.width + 1,
    );
    await expectNoA11yViolations(page);
    await page.screenshot({
      path: path.join(outDir, `document-${viewport.name}.png`),
      fullPage: true,
    });
  }

  await page.setViewportSize({ width: 1366, height: 768 });
  await page.getByRole("button", { name: "Todos los hallazgos" }).click();
  await expect(page.getByTestId("technical-view-banner")).toBeVisible();
  await expect(page.getByTestId("knowledge-document-insight")).toHaveCount(0);
  await page.screenshot({
    path: path.join(outDir, "technical-1366.png"),
    fullPage: true,
  });
});
