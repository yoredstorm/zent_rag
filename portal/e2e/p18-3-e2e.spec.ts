import fs from "fs";
import path from "path";
import { expect, test } from "@playwright/test";
import { expectNoA11yViolations } from "./fixtures";

/**
 * P18.3-07 - E2E real de ingesta con worker, sesión durable y PDF.
 * Requiere API + worker + Postgres + Qdrant. No usa interceptores de red.
 */
test.skip(
  process.env.P18_3_E2E_INGEST !== "1",
  "Requiere worker de ingesta; se ejecuta en el job de integración.",
);

test("P18.3 ingesta PDF/CSV, rechazo de MIME, sesión durable y Explorador", async ({
  page,
  request,
}) => {
  test.setTimeout(360_000);
  const stamp = Date.now();
  const signup = await request.post("/api/v1/auth/signup", {
    data: {
      company_name: `P183 E2E ${stamp}`,
      email: `p183-e2e-${stamp}@example.com`,
      password: "P183-e2e-password-123",
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
    data: { name: "P18.3 E2E" },
  });
  expect(corpusResponse.ok()).toBeTruthy();
  const corpus = (await corpusResponse.json()) as { corpus: { id: string } };

  const learning = await request.post("/api/v1/knowledge/sessions", {
    headers,
    data: { title: "P18.3 ingesta real", origin: "p18-3-e2e" },
  });
  expect(learning.ok()).toBeTruthy();
  const learningSession = (await learning.json()) as { session_id: string };

  const upload = async (name: string, mimeType: string, buffer: Buffer) =>
    request.post(
      `/api/v1/sources/files/upload?corpus_id=${corpus.corpus.id}&session_id=${learningSession.session_id}`,
      {
        headers: { ...headers, "Idempotency-Key": crypto.randomUUID() },
        multipart: { file: { name, mimeType, buffer } },
      },
    );

  const pdf = await upload(
    "p18-3-atpco.pdf",
    "application/pdf",
    fs.readFileSync(path.join(process.cwd(), "e2e", "fixtures", "p18-3-atpco.pdf")),
  );
  const pdfBody = await pdf.text();
  expect(pdf.status(), pdfBody).toBe(201);
  const pdfSource = JSON.parse(pdfBody) as { id: string };

  const csv = await upload(
    "p18-3-productos.csv",
    "text/csv",
    fs.readFileSync(path.join(process.cwd(), "e2e", "fixtures", "productos.csv")),
  );
  const csvBody = await csv.text();
  expect(csv.status(), csvBody).toBe(201);
  const csvSource = JSON.parse(csvBody) as { id: string };

  const rejected = await upload(
    "p18-3-malware.exe",
    "application/x-msdownload",
    Buffer.from("MZ no es un documento"),
  );
  expect([400, 415]).toContain(rejected.status());

  let sources: { id: string; status: string; name?: string }[] = [];
  for (let attempt = 0; attempt < 240; attempt += 1) {
    const detail = await request.get(
      `/api/v1/knowledge/workspaces/${corpus.corpus.id}`,
      { headers },
    );
    if (detail.ok()) {
      sources = ((await detail.json()) as { sources: { id: string; status: string }[] })
        .sources;
      if (
        sources.find((item) => item.id === pdfSource.id)?.status === "indexed" &&
        ["indexed", "error"].includes(
          sources.find((item) => item.id === csvSource.id)?.status ?? "",
        )
      ) {
        break;
      }
    }
    await page.waitForTimeout(1000);
  }
  expect(
    sources.find((item) => item.id === pdfSource.id)?.status,
    "el PDF debe terminar indexed",
  ).toBe("indexed");
  expect(sources.find((item) => item.id === csvSource.id)?.status).not.toBe("created");
  expect(sources.find((item) => item.id === pdfSource.id)).toBeTruthy();
  expect(sources.some((item) => item.name?.includes("malware"))).toBeFalsy();

  const sessionDetail = await request.get(
    `/api/v1/knowledge/sessions/${learningSession.session_id}`,
    { headers },
  );
  expect(sessionDetail.ok()).toBeTruthy();
  const detailPayload = (await sessionDetail.json()) as {
    session_id: string;
    source_count: number;
    sources: { source_id: string }[];
  };
  expect(detailPayload.source_count).toBeGreaterThanOrEqual(2);
  expect(detailPayload.sources.map((item) => item.source_id)).toEqual(
    expect.arrayContaining([pdfSource.id, csvSource.id]),
  );

  const file = await request.get(
    `/api/v1/knowledge/workspaces/${corpus.corpus.id}/sources/${pdfSource.id}/file`,
    { headers },
  );
  expect(file.status()).toBe(200);
  expect(file.headers()["content-type"]).toContain("pdf");

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

  await page.goto(`/knowledge/sessions/${learningSession.session_id}`, {
    waitUntil: "domcontentloaded",
  });
  await expect(page.getByTestId("learning-session")).toBeVisible({ timeout: 30_000 });
  await page.reload({ waitUntil: "domcontentloaded" });
  await expect(page.getByTestId("learning-session")).toBeVisible({ timeout: 30_000 });
  await expect(page.getByTestId("learning-session")).toContainText("fuente", {
    timeout: 30_000,
  });

  const outDir = path.join(
    process.cwd(),
    "..",
    "artifacts",
    "certification",
    "p18-3",
    "e2e",
  );
  fs.mkdirSync(outDir, { recursive: true });
  for (const viewport of [
    { name: "1366", width: 1366, height: 768 },
    { name: "390", width: 390, height: 844 },
  ]) {
    await page.setViewportSize({ width: viewport.width, height: viewport.height });
    await page.goto(`/knowledge/explorer?source=${pdfSource.id}`, {
      waitUntil: "domcontentloaded",
    });
    await expect(page.getByTestId("knowledge-document-insight")).toBeVisible({
      timeout: 30_000,
    });
    await expect(page.getByTestId("document-passages")).toBeVisible({
      timeout: 30_000,
    });
    const bodyWidth = await page.evaluate(() => document.body.scrollWidth);
    expect(bodyWidth, `${viewport.name}px sin overflow`).toBeLessThanOrEqual(
      viewport.width + 1,
    );
    await expectNoA11yViolations(page);
    await page.screenshot({
      path: path.join(outDir, `pdf-explorer-${viewport.name}.png`),
      fullPage: true,
    });
  }

});

