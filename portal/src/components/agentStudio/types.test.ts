import { describe, expect, it } from "vitest";
import {
  ADVANCED_GROUPS,
  DEFAULT_RESPONSE_PROFILE,
  RESPONSE_PROFILE_PRESETS,
  isAdvancedGroup,
  legacyTabToGroup,
  resolveStudioView,
} from "./types";

describe("resolveStudioView", () => {
  it("sin parámetros abre Desarrollar sin detalle avanzado", () => {
    expect(resolveStudioView(null, null)).toEqual({
      stage: "develop",
      publishFocus: null,
      advancedOpen: false,
      advancedGroup: null,
    });
  });

  it("mantiene el panel de prueba", () => {
    expect(resolveStudioView("test", null).stage).toBe("test");
  });

  it("acepta el alias legacy configure", () => {
    expect(resolveStudioView("configure", null).stage).toBe("develop");
  });

  it("abre Avanzado con un tab que sigue siendo grupo", () => {
    expect(resolveStudioView("advanced", "tools")).toMatchObject({
      stage: "develop",
      advancedOpen: true,
      advancedGroup: "tools",
    });
  });

  it("abre Avanzado aunque el panel no lo diga, si el tab es un grupo", () => {
    expect(resolveStudioView(null, "retrieval")).toMatchObject({
      stage: "develop",
      advancedOpen: true,
      advancedGroup: "retrieval",
    });
  });

  it("con panel advanced y sin tab deja todos los grupos plegados", () => {
    const view = resolveStudioView("advanced", null);
    expect(view.advancedOpen).toBe(true);
    expect(view.advancedGroup).toBeNull();
  });

  it("maneja las 11 pestañas antiguas: las de publicación van a Publicar", () => {
    for (const tab of ["publish", "readiness", "evaluation", "versions", "deployments", "embed"]) {
      const view = resolveStudioView(null, tab);
      expect(view.stage).toBe("publish");
      expect(view.advancedOpen).toBe(false);
    }
    expect(resolveStudioView("advanced", "versions").stage).toBe("publish");
    expect(resolveStudioView("advanced", "readiness")).toMatchObject({
      stage: "publish",
      publishFocus: "readiness",
    });
  });

  it("maneja las 11 pestañas antiguas: las de configuración van a su grupo", () => {
    expect(resolveStudioView("advanced", "behavior").advancedGroup).toBe("model");
    expect(resolveStudioView("advanced", "model").advancedGroup).toBe("model");
    expect(resolveStudioView("advanced", "output").advancedGroup).toBe("integration");
    expect(resolveStudioView("advanced", "capabilities").advancedGroup).toBe("tools");
    expect(resolveStudioView("advanced", "security").advancedGroup).toBe("tools");
    expect(resolveStudioView("advanced", "limits").advancedGroup).toBe("limits");
  });
});

describe("legacyTabToGroup", () => {
  it("acepta los grupos actuales tal cual", () => {
    for (const group of ADVANCED_GROUPS) {
      expect(legacyTabToGroup(group)).toBe(group);
      expect(isAdvancedGroup(group)).toBe(true);
    }
  });

  it("devuelve null cuando no hay tab, es desconocida o es de publicación", () => {
    expect(legacyTabToGroup(null)).toBeNull();
    expect(legacyTabToGroup("")).toBeNull();
    expect(legacyTabToGroup("no-existe")).toBeNull();
    expect(legacyTabToGroup("versions")).toBeNull();
  });
});

describe("perfil de respuesta por defecto", () => {
  it("refleja los defaults del dominio (si no, la UI miente en agentes legacy)", () => {
    expect(DEFAULT_RESPONSE_PROFILE).toMatchObject({
      language: "es",
      tone: "professional",
      technical_level: "intermediate",
      default_detail: "normal",
      audience: "technical",
      conclusion_first: true,
      use_headings: true,
      use_bold: true,
      use_tables: true,
      use_examples: true,
      cite_sources: true,
      show_uncertainty: true,
      show_practical_implications: true,
      preserve_domain_terms: true,
      custom_instructions: "",
    });
  });

  it("expone un preset equilibrado como estado recomendado", () => {
    expect(RESPONSE_PROFILE_PRESETS[0].id).toBe("balanced");
    expect(RESPONSE_PROFILE_PRESETS[0].profile).toEqual({ use_tables: true });
  });
});
