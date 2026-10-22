import { describe, expect, it } from "vitest";
import { marketplaceHref, safeReturnTo } from "./marketplaceReturn";

describe("safeReturnTo", () => {
  it("acepta el estudio y rechaza redirecciones externas", () => {
    expect(safeReturnTo("/workflows/abc-1")).toBe("/workflows/abc-1");
    expect(safeReturnTo("/workflows/new/manual?plantilla=mentor")).toBe(
      "/workflows/new/manual?plantilla=mentor",
    );
    expect(safeReturnTo("https://evil.example/workflows")).toBeNull();
    expect(safeReturnTo("//evil.example")).toBeNull();
    expect(safeReturnTo("/\\evil")).toBeNull();
    expect(safeReturnTo("/workflows?next=https://evil.example")).toBeNull();
    expect(safeReturnTo("javascript:alert(1)")).toBeNull();
  });

  it("arma el deep link solo con parámetros seguros", () => {
    const href = marketplaceHref({
      slug: "demo-echo",
      capabilityRef: "payments.checkout.create",
      returnTo: "/workflows/wf-1",
      nodeId: "n1",
      designSessionId: "sess-1",
    });
    expect(href.startsWith("/marketplace?")).toBe(true);
    expect(href).toContain("return_to=%2Fworkflows%2Fwf-1");
    expect(href).toContain("capability_ref=payments.checkout.create");
    expect(href).not.toContain("http");

    const blocked = marketplaceHref({
      slug: "demo-echo",
      returnTo: "https://evil.example",
      nodeId: "../admin",
      capabilityRef: "https://evil",
    });
    expect(blocked).not.toContain("return_to");
    expect(blocked).not.toContain("node_id");
    expect(blocked).not.toContain("capability_ref");
  });
});
