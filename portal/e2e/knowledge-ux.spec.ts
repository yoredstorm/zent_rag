import { expect, test } from "@playwright/test";
import { expectNoA11yViolations } from "./fixtures";

test("P17 smoke: Preguntar y Mejorar sin violaciones graves", async ({
  page,
  request,
}) => {
  const stamp = Date.now();
  const signup = await request.post("/api/v1/auth/signup", {
    data: {
      company_name: `P17 UX ${stamp}`,
      email: `p17-ux-${stamp}@example.com`,
      password: "P17-ux-password-123",
    },
  });
  expect(signup.ok()).toBeTruthy();
  const session = (await signup.json()) as {
    access_token: string;
    organization_id: string;
    company_name: string;
    email: string;
  };
  const headers = {
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

  await page.setViewportSize({ width: 1280, height: 900 });
  await page.goto("/knowledge/ask");
  await expect(page.getByRole("heading", { name: "Preguntar" })).toBeVisible({
    timeout: 30_000,
  });
  await expectNoA11yViolations(page);

  await page.goto("/knowledge/improve");
  await expect(page.getByRole("heading", { name: "Mejorar" })).toBeVisible({
    timeout: 30_000,
  });
  await expect(page.getByTestId("quality-inbox")).toBeVisible();
  await expectNoA11yViolations(page);
});
