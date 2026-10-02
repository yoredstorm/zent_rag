import { visiblePlatformNav, PLATFORM_NAV } from "../lib/platformNav";
import { describe, expect, it } from "vitest";

describe("visiblePlatformNav", () => {
  it("devuelve todo cuando no hay permisos (fail-open visual)", () => {
    expect(visiblePlatformNav(undefined)).toEqual(PLATFORM_NAV);
    expect(visiblePlatformNav([])).toEqual(PLATFORM_NAV);
  });

  it("filtra items sin permiso y grupos vacíos", () => {
    const out = visiblePlatformNav(["audit.read"]);
    // Security (platform.users.manage) y Settings (platform.settings.manage) deben quedar fuera.
    const platform = out.find((g) => g.label === "Platform");
    expect(platform?.items.find((i) => i.label === "Security")).toBeUndefined();
    expect(platform?.items.find((i) => i.label === "Settings")).toBeUndefined();
    // Audit sí, bajo Trust.
    const trust = out.find((g) => g.label === "Trust");
    expect(trust?.items.find((i) => i.label === "Audit")).toBeDefined();
    // Tenants (tenant.read) no concedido -> Business sin ese item.
    const business = out.find((g) => g.label === "Business");
    expect(business?.items.find((i) => i.label === "Tenants")).toBeUndefined();
  });

  it("super_admin (permiso '*') ve todo", () => {
    const out = visiblePlatformNav(["*"]);
    expect(out).toEqual(PLATFORM_NAV);
  });
});
