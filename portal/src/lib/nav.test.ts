import { describe, expect, it } from "vitest";
import type { Session } from "../api";
import { canSeeNavItem, visibleNavLeaves } from "./nav";

function session(roles: string[], permissions: string[] = []): Session {
  return {
    token: "rag_sess_test",
    organizationId: "org-1",
    companyName: "Acme",
    email: "a@b.cl",
    roles,
    permissions,
  };
}

describe("canSeeNavItem — RBAC de navegación", () => {
  it("oculta Claves y Equipo salvo owner/admin", () => {
    for (const key of ["keys", "users"]) {
      expect(canSeeNavItem(session(["owner"]), key)).toBe(true);
      expect(canSeeNavItem(session(["admin"]), key)).toBe(true);
      expect(canSeeNavItem(session(["member"]), key)).toBe(false);
      expect(canSeeNavItem(session(["viewer"]), key)).toBe(false);
      expect(canSeeNavItem(null, key)).toBe(false);
    }
  });

  it("Billing y Settings solo org-admin", () => {
    for (const key of ["billing", "settings"]) {
      expect(canSeeNavItem(session(["owner"]), key)).toBe(true);
      expect(canSeeNavItem(session(["admin"]), key)).toBe(true);
      expect(canSeeNavItem(session(["member"]), key)).toBe(false);
    }
  });

  it("Audit: org-admin o permiso audit:read", () => {
    expect(canSeeNavItem(session(["member"]), "audit")).toBe(false);
    expect(canSeeNavItem(session(["member"], ["audit:read"]), "audit")).toBe(true);
    expect(canSeeNavItem(session(["viewer"], ["audit:read"]), "audit")).toBe(true);
  });

  it("prompts/connectors ocultos para viewer-only", () => {
    expect(canSeeNavItem(session(["member"]), "prompts")).toBe(true);
    expect(canSeeNavItem(session(["viewer"]), "prompts")).toBe(false);
    expect(canSeeNavItem(session(["viewer"]), "connectors")).toBe(false);
  });

  it("eval_ui gated por entitlement", () => {
    expect(canSeeNavItem(session(["owner"]), "eval_ui", { eval_ui: true })).toBe(true);
    expect(canSeeNavItem(session(["owner"]), "eval_ui", { eval_ui: false })).toBe(false);
    expect(canSeeNavItem(session(["owner"]), "eval_ui", {})).toBe(false);
  });

  it("ítems sin key son visibles para todos", () => {
    expect(canSeeNavItem(null, undefined)).toBe(true);
    expect(canSeeNavItem(session(["viewer"]), undefined)).toBe(true);
  });
});

describe("visibleNavLeaves", () => {
  it("filtra por rol y entitlements", () => {
    const viewer = session(["viewer"]);
    const leaves = visibleNavLeaves(viewer, { eval_ui: true });
    const paths = leaves.map((l) => l.to);
    expect(paths).toContain("/");
    expect(paths).toContain("/chat");
    expect(paths).not.toContain("/keys");
    expect(paths).not.toContain("/team");
    expect(paths).not.toContain("/prompts");
    expect(paths).toContain("/evaluation");
  });

  it("sin sesión solo muestra ítems públicos", () => {
    const leaves = visibleNavLeaves(null, {});
    const paths = leaves.map((l) => l.to);
    expect(paths).not.toContain("/keys");
    expect(paths).not.toContain("/evaluation");
  });
});