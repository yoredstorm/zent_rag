import { describe, expect, it } from "vitest";
import { hasUnpublishedChanges, lifecycleIndicator, missionSummary, persistenceIndicator } from "./studioState";

describe("persistenceIndicator", () => {
  it("prioriza guardando > error > sin guardar > guardado > limpio", () => {
    expect(persistenceIndicator({ dirty: true, saving: true, saveError: "x" }).key).toBe("saving");
    expect(persistenceIndicator({ dirty: true, saving: false, saveError: "Sin conexión" })).toMatchObject({
      key: "error",
      tone: "danger",
      detail: "Sin conexión",
    });
    expect(persistenceIndicator({ dirty: true, saving: false }).label).toBe("Cambios sin guardar");
    expect(persistenceIndicator({ dirty: false, saving: false, justSaved: true }).label).toBe("Guardado");
    expect(persistenceIndicator({ dirty: false, saving: false }).label).toBe("Borrador guardado");
  });
});

describe("lifecycleIndicator", () => {
  it("borrador nunca se presenta como publicado ni activo", () => {
    const draft = lifecycleIndicator({ status: "draft" });
    expect(draft.label).toBe("Borrador sin publicar");
    expect(draft.label).not.toMatch(/activo|publicado ·/i);
  });

  it("publicado activo o pausado muestra versión y avisa del borrador pendiente", () => {
    expect(lifecycleIndicator({ status: "active", publishedVersion: 3 }).label).toBe("Publicado v3 · activo");
    expect(lifecycleIndicator({ status: "active", publishedVersion: 3 }).detail).toBeUndefined();
    expect(lifecycleIndicator({ status: "paused", publishedVersion: 2, dirty: true })).toMatchObject({
      label: "Publicado v2 · pausado",
      tone: "warn",
      detail: expect.stringContaining("no están publicados"),
    });
    expect(lifecycleIndicator({ status: "archived" }).label).toBe("Archivado");
  });

  it("hasUnpublishedChanges solo aplica a flujos publicados", () => {
    expect(hasUnpublishedChanges({ status: "draft", dirty: true })).toBe(false);
    expect(hasUnpublishedChanges({ status: "active", draftChanged: true })).toBe(true);
    expect(hasUnpublishedChanges({ status: "active" })).toBe(false);
  });
});

describe("missionSummary", () => {
  it("usa el objetivo; si falta, rol y público; vacío si no hay ficha", () => {
    expect(missionSummary({ goal: " Entregar pedidos a tiempo ", role: "Despacho" })).toBe("Entregar pedidos a tiempo");
    expect(missionSummary({ role: "Mentor", audience: "alumnos" })).toBe("Mentor para alumnos");
    expect(missionSummary({ role: "Mentor" })).toBe("Mentor");
    expect(missionSummary({})).toBe("");
  });
});
