import { afterEach, describe, expect, it } from "vitest";
import type { Session } from "../api";
import {
  PRODUCT_TOUR_STORAGE_KEY,
  TOUR_STEPS,
  filterTourSteps,
  markCompleted,
  markSkipped,
  readTourStatus,
  requestProductTourStart,
  shouldAutoStart,
  tourTargetForGroup,
  tourTargetForPath,
  visibleTourTarget,
} from "./productTour";

function session(roles: string[]): Session {
  return {
    token: "rag_sess_test",
    organizationId: "org-1",
    companyName: "Acme",
    email: "a@b.cl",
    roles,
  };
}

describe("TOUR_STEPS", () => {
  it("cubre el recorrido híbrido en orden", () => {
    expect(TOUR_STEPS.map((s) => s.id)).toEqual([
      "dashboard",
      "build",
      "playground",
      "agents",
      "knowledge",
      "workflows",
      "operate",
      "usage",
      "ai-quality",
      "deployments",
      "environments",
      "developers-group",
      "keys",
      "webhooks",
      "developers-center",
      "mcp",
      "organization",
      "team",
      "billing",
      "security",
      "settings",
      "advanced",
      "workspace",
      "search",
    ]);
  });

  it("cada paso tiene título y cuerpo explicativo en español", () => {
    for (const step of TOUR_STEPS) {
      expect(step.title.trim().length).toBeGreaterThan(2);
      expect(step.body.trim().length).toBeGreaterThan(80);
    }
  });
});

describe("filterTourSteps", () => {
  it("owner ve claves, workflows, webhooks y equipo", () => {
    const targets = filterTourSteps(session(["owner"])).map((s) => s.target);
    expect(targets).toContain("nav-keys");
    expect(targets).toContain("nav-workflows");
    expect(targets).toContain("nav-webhooks");
    expect(targets).toContain("nav-team");
  });

  it("viewer omite claves y admin; conserva playground y centro de desarrolladores", () => {
    const targets = filterTourSteps(session(["viewer"]));
    const ids = targets.map((s) => s.target);
    expect(ids).not.toContain("nav-keys");
    expect(ids).not.toContain("nav-webhooks");
    expect(ids).not.toContain("nav-team");
    expect(ids).not.toContain("nav-billing");
    expect(ids).not.toContain("nav-settings");
    expect(ids).toContain("nav-developers");
    expect(ids).toContain("nav-chat");
  });
});

describe("persistencia del tour", () => {
  afterEach(() => {
    window.localStorage.removeItem(PRODUCT_TOUR_STORAGE_KEY);
  });

  it("shouldAutoStart es true si no hay clave", () => {
    expect(readTourStatus()).toBeNull();
    expect(shouldAutoStart()).toBe(true);
  });

  it("shouldAutoStart es false tras skip o complete", () => {
    markSkipped();
    expect(readTourStatus()).toEqual({ status: "skipped" });
    expect(shouldAutoStart()).toBe(false);

    window.localStorage.removeItem(PRODUCT_TOUR_STORAGE_KEY);
    markCompleted();
    expect(readTourStatus()).toEqual({ status: "completed" });
    expect(shouldAutoStart()).toBe(false);
  });
});

describe("visibleTourTarget", () => {
  it("elige el nodo visible cuando hay duplicados", () => {
    const hidden = document.createElement("div");
    hidden.setAttribute("data-tour", "nav-dashboard");
    hidden.getBoundingClientRect = () =>
      ({ width: 0, height: 0, top: 0, left: 0, bottom: 0, right: 0, x: 0, y: 0, toJSON: () => ({}) }) as DOMRect;

    const shown = document.createElement("div");
    shown.setAttribute("data-tour", "nav-dashboard");
    shown.getBoundingClientRect = () =>
      ({
        width: 120,
        height: 32,
        top: 80,
        left: 16,
        bottom: 112,
        right: 136,
        x: 16,
        y: 80,
        toJSON: () => ({}),
      }) as DOMRect;

    document.body.append(hidden, shown);
    expect(visibleTourTarget("nav-dashboard")).toBe(shown);
    hidden.remove();
    shown.remove();
  });

  it("devuelve null si nadie tiene tamaño", () => {
    expect(visibleTourTarget("missing")).toBeNull();
  });
});

describe("requestProductTourStart", () => {
  it("dispara el evento de replay", () => {
    let received = false;
    const onStart = () => {
      received = true;
    };
    window.addEventListener("zent:product-tour-start", onStart);
    requestProductTourStart();
    window.removeEventListener("zent:product-tour-start", onStart);
    expect(received).toBe(true);
  });
});

describe("tourTarget helpers", () => {
  it("mapea rutas y grupos a data-tour", () => {
    expect(tourTargetForPath("/")).toBe("nav-dashboard");
    expect(tourTargetForPath("/chat")).toBe("nav-chat");
    expect(tourTargetForPath("/keys")).toBe("nav-keys");
    expect(tourTargetForPath("/billing")).toBe("nav-billing");
    expect(tourTargetForPath("/workflows")).toBe("nav-workflows");
    expect(tourTargetForGroup("Construir")).toBe("nav-group-construir");
    expect(tourTargetForGroup("Desarrolladores")).toBe("nav-group-desarrolladores");
    expect(tourTargetForGroup("Avanzado")).toBe("nav-group-avanzado");
    expect(tourTargetForGroup("Panel general")).toBeUndefined();
  });
});
