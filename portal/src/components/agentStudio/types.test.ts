import { describe, expect, it } from "vitest";
import { ADVANCED_TABS, isAdvancedTab, legacyTabToGroup } from "./types";

describe("legacyTabToGroup", () => {
  it("mantiene los tres grupos actuales", () => {
    expect(ADVANCED_TABS).toEqual(["behavior", "capabilities", "publish"]);
    for (const tab of ADVANCED_TABS) {
      expect(legacyTabToGroup(tab)).toBe(tab);
      expect(isAdvancedTab(tab)).toBe(true);
    }
  });

  it("mapea las pestañas antiguas a su grupo", () => {
    expect(legacyTabToGroup("model")).toBe("behavior");
    expect(legacyTabToGroup("output")).toBe("behavior");
    expect(legacyTabToGroup("tools")).toBe("capabilities");
    expect(legacyTabToGroup("security")).toBe("capabilities");
    expect(legacyTabToGroup("retrieval")).toBe("capabilities");
    expect(legacyTabToGroup("limits")).toBe("capabilities");
    expect(legacyTabToGroup("readiness")).toBe("publish");
    expect(legacyTabToGroup("evaluation")).toBe("publish");
    expect(legacyTabToGroup("versions")).toBe("publish");
    expect(legacyTabToGroup("deployments")).toBe("publish");
    expect(legacyTabToGroup("embed")).toBe("publish");
  });

  it("devuelve null cuando no hay tab o es desconocida", () => {
    expect(legacyTabToGroup(null)).toBeNull();
    expect(legacyTabToGroup("")).toBeNull();
    expect(legacyTabToGroup("no-existe")).toBeNull();
  });
});
