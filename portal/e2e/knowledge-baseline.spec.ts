import fs from "fs";
import path from "path";
import { fileURLToPath } from "url";
import { expect, test } from "@playwright/test";

/**
 * Baseline P17-00. Requiere un stack con worker de ingesta, Qdrant y proveedor
 * real (o el fallback configurado). En CI se omite por defecto porque el job
 * portal-e2e no levanta el worker; el recorrido se ejecuta en Docker/local.
 */
const ENABLED = process.env.E2E_KNOWLEDGE_BASELINE === "1";
const PDF = path.join(
  path.dirname(fileURLToPath(import.meta.url)),
  "..",
  "..",
  "artifacts",
  "pdf-parser-benchmark",
  "corpus",
  "atpco.pdf",
);
const sleep = (ms: number) => new Promise((resolve) => setTimeout(resolve, ms));

test.describe("P17-00 baseline de conocimiento", () => {
  test.skip(!ENABLED, "Definir E2E_KNOWLEDGE_BASELINE=1 con worker de ingesta activo");

  test("espacio, PDF, ingesta, cita, conflicto y aislamiento", async ({
    page,
    request,
  }) => {
    test.setTimeout(420_000);
    const stamp = Date.now();
    const email = `p17-baseline-${stamp}@example.com`;
    const signup = await request.post("/api/v1/auth/signup", {
      data: {
        company_name: `P17 Baseline ${stamp}`,
        email,
        password: "P17-baseline-password-123",
      },
    });
    expect(signup.ok()).toBeTruthy();
    const session = (await signup.json()) as {
      access_token: string;
      organization_id: string;
      company_name: string;
      email: string;
    };
    const headers: Record<string, string> = {
      Authorization: `Bearer ${session.access_token}`,
      "X-Organization-Id": session.organization_id,
      "Content-Type": "application/json",
    };
    const start = await request.post("/api/v1/onboarding/start-mode", {
      headers: { ...headers, "Idempotency-Key": crypto.randomUUID() },
      data: { mode: "blank" },
    });
    expect(start.ok()).toBeTruthy();
    const workspace = (await start.json()) as { workspace_id: string; kind: string };
    headers["X-Workspace-Id"] = workspace.workspace_id;

    await page.addInitScript(
      ({ token, organizationId, companyName, userEmail, workspaceId, workspaceKind }) => {
        sessionStorage.setItem("rag_portal_token", token);
        localStorage.setItem("rag_portal_org", organizationId);
        localStorage.setItem("rag_portal_company", companyName);
        localStorage.setItem("rag_portal_email", userEmail);
        localStorage.setItem("rag_portal_workspace", workspaceId);
        localStorage.setItem("rag_portal_workspace_kind", workspaceKind);
        localStorage.setItem("zent_product_tour_v2", JSON.stringify({ status: "completed" }));
      },
      {
        token: session.access_token,
        organizationId: session.organization_id,
        companyName: session.company_name,
        userEmail: session.email,
        workspaceId: workspace.workspace_id,
        workspaceKind: workspace.kind,
      },
    );
    await page.setViewportSize({ width: 1440, height: 900 });

    const corpusResponse = await request.post("/api/v1/knowledge/workspaces", {
      headers: { ...headers, "Idempotency-Key": crypto.randomUUID() },
      data: { name: `P17 Baseline ${stamp}` },
    });
    expect(corpusResponse.ok()).toBeTruthy();
    const corpus = (await corpusResponse.json()) as { corpus: { id: string } };

    const upload = await request.post(
      `/api/v1/sources/files/upload-batch?corpus_id=${corpus.corpus.id}`,
      {
      headers: {
        Authorization: headers.Authorization,
        "X-Organization-Id": headers["X-Organization-Id"],
        "X-Workspace-Id": headers["X-Workspace-Id"],
        "Idempotency-Key": crypto.randomUUID(),
      },
      multipart: {
        files: {
          name: "atpco.pdf",
          mimeType: "application/pdf",
          buffer: fs.readFileSync(PDF),
        },
      },
    });
    const uploadText = await upload.text();
    expect(upload.ok(), uploadText).toBeTruthy();
    const uploadBody = JSON.parse(uploadText) as {
      items: { status: string; source_id?: string; job_id?: string }[];
      session_id?: string;
    };
    const created = uploadBody.items.find((item) => item.status === "created");
    expect(created?.source_id, "el PDF debe crear una fuente").toBeTruthy();
    const sourceId = created!.source_id!;
    const sessionId = uploadBody.session_id;
    expect(sessionId, "la subida debe abrir una sesión").toBeTruthy();
    console.log("P17 baseline: uploaded", { sourceId, sessionId });

    try {
      let sessionStatus = "";
      let sourceStatus = "";
      for (let attempt = 0; attempt < 90; attempt += 1) {
        const sourceDetail = await request.get(`/api/v1/sources/${sourceId}`, {
          headers,
        });
        expect(sourceDetail.ok()).toBeTruthy();
        sourceStatus = String((await sourceDetail.json()).status || "");
        const detail = await request.get(
          `/api/v1/knowledge/sessions/${sessionId}`,
          { headers },
        );
        expect(detail.ok()).toBeTruthy();
        const body = (await detail.json()) as {
          status: string;
          sources?: { status?: string }[];
        };
        sessionStatus = body.status;
        if (sourceStatus === "indexed" || sourceStatus === "ready") break;
        if (["available", "completed", "partial"].includes(sessionStatus)) break;
        if (sourceStatus === "error" || sessionStatus === "failed") {
          throw new Error(
            `la ingesta falló (fuente ${sourceStatus || "sin estado"}, sesión ${sessionStatus || "sin estado"})`,
          );
        }
        await sleep(2000);
      }
      expect(
        ["indexed", "ready"].includes(sourceStatus) ||
          ["available", "completed", "partial"].includes(sessionStatus),
        `la ingesta no quedó disponible (fuente ${sourceStatus || "sin estado"}, sesión ${sessionStatus || "sin estado"})`,
      ).toBeTruthy();
      test.info().annotations.push({
        type: "readiness_signal",
        description: `source=${sourceStatus || "unknown"}; session=${sessionStatus || "unknown"}`,
      });
      console.log("P17 baseline: readiness", { sourceStatus, sessionStatus });

      const chat = await request.post(
        `/api/v1/knowledge/workspaces/${corpus.corpus.id}/chat`,
        {
          headers: { ...headers, "Idempotency-Key": crypto.randomUUID() },
          data: {
            query: "¿Qué información contiene el documento?",
            source_ids: [sourceId],
          },
        },
      );
      expect(chat.ok()).toBeTruthy();
      const chatJson = (await chat.json()) as {
        grounded: {
          answer: string;
          citations: { page: number | null; locator: string; excerpt: string; document_id: string | null }[];
        };
      };
      const grounded = chatJson;
      expect(grounded.grounded.answer.length).toBeGreaterThan(0);
      expect(grounded.grounded.citations.length, "debe devolver una cita real").toBeGreaterThan(0);
      expect(grounded.grounded.citations[0].page).toBeGreaterThan(0);
      expect(grounded.grounded.citations[0].locator.length).toBeGreaterThan(0);
      console.log("P17 baseline: citations", grounded.grounded.citations.length);

      await page.goto(`/knowledge/workspaces/${corpus.corpus.id}`, {
        waitUntil: "domcontentloaded",
        timeout: 30_000,
      });
      console.log("P17 baseline: navigated to workspace");
      const question = page.getByPlaceholder("Haz una pregunta sobre el corpus…");
      await expect(question).toBeVisible({ timeout: 30_000 });
      await expect(
        page.getByRole("button", { name: /atpco\.pdf/i }).first(),
      ).toBeVisible({ timeout: 30_000 });
      test.info().annotations.push({
        type: "citation_ui",
        description:
          "source linked to corpus; viewer remains the existing workspace PDF viewer",
      });
      console.log("P17 baseline: source linked to corpus");

      const conflicts = await request.get("/api/v1/knowledge/conflicts?status=open", {
        headers,
      });
      expect(conflicts.ok()).toBeTruthy();
      const conflictBody = (await conflicts.json()) as { items?: unknown[]; conflicts?: unknown[] };
      const count = (conflictBody.items || conflictBody.conflicts || []).length;
      test.info().annotations.push({
        type: "conflict_scenario",
        description: count > 0 ? `open=${count}` : "NOT_AVAILABLE",
      });

      const crossTenant = await request.get(
        `/api/v1/knowledge/workspaces/${corpus.corpus.id}`,
        {
          headers: {
            ...headers,
            "X-Organization-Id": crypto.randomUUID(),
          },
        },
      );
      expect([401, 403, 404]).toContain(crossTenant.status());
      test.info().annotations.push({
        type: "citation_ui",
        description: "Sources used visible; viewer de cita queda para P17-04",
      });
    } finally {
      await request.delete(`/api/v1/sources/${sourceId}`, {
        headers: { ...headers, "Idempotency-Key": crypto.randomUUID() },
      });
    }
  });
});
