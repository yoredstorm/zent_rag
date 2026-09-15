import { describe, expect, it } from "vitest";
import type { Session } from "../api";
import { NAV_GROUPS, canSeeNavItem, navLeaves, visibleNavLeaves } from "./nav";

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

describe("NAV_GROUPS", () => {
  it("pone Asistentes primero en Operar, no en Construir", () => {
    const construir = NAV_GROUPS.find((g) => g.label === "Construir");
    const operar = NAV_GROUPS.find((g) => g.label === "Operar");
    expect(construir?.items?.map((item) => item.to)).not.toContain("/assistants");
    expect(construir?.items?.map((item) => item.to)).toContain("/agents");
    expect(operar?.items?.[0]).toMatchObject({ to: "/assistants", label: "Asistentes" });
  });

  it("mantiene los clusters del modelo mental en orden", () => {
    expect(NAV_GROUPS.map((g) => g.label)).toEqual([
      "Inicio",
      "Conocimiento",
      "Construir",
      "Operar",
      "Evaluar",
      "Desarrollar",
      "Gobernar",
      "Gestionar",
    ]);
  });

  it("no duplica rutas y conserva el gating de las hojas", () => {
    const leaves = NAV_GROUPS.flatMap(navLeaves);
    const paths = leaves.map((l) => l.to);
    expect(new Set(paths).size).toBe(paths.length);
    expect(leaves.find((l) => l.to === "/keys")?.key).toBe("keys");
    expect(leaves.find((l) => l.to === "/evaluation")?.key).toBe("eval_ui");
    expect(leaves.find((l) => l.to === "/security")?.key).toBe("audit");
  });

  it("Gestionar arranca colapsado y es la única sección colapsable", () => {
    const collapsibles = NAV_GROUPS.filter((g) => g.collapsible).map((g) => g.label);
    expect(collapsibles).toEqual(["Gestionar"]);
    expect(NAV_GROUPS.find((g) => g.label === "Gestionar")?.defaultCollapsed).toBe(true);
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