import { describe, expect, it } from "vitest";
import {
  MAX_ZOOM,
  MIN_ZOOM,
  NODE_H,
  NODE_W,
  centerOn,
  clampZoom,
  detailLevel,
  fitRect,
  loadViewport,
  nodesBounds,
  rectFromPoints,
  rectsIntersect,
  revealRect,
  saveViewport,
  viewportStorageKey,
  visibleWorldRect,
  wheelIntent,
  zoomAt,
} from "./canvasViewport";

const wheel = (patch: Partial<Parameters<typeof wheelIntent>[0]>) =>
  wheelIntent({ deltaX: 0, deltaY: 0, deltaMode: 0, ctrlKey: false, metaKey: false, shiftKey: false, ...patch });

describe("canvasViewport", () => {
  it("limita el zoom al rango permitido", () => {
    expect(clampZoom(10)).toBe(MAX_ZOOM);
    expect(clampZoom(0.01)).toBe(MIN_ZOOM);
    expect(clampZoom(Number.NaN)).toBe(1);
  });

  it("zoomAt mantiene fijo el punto bajo el cursor", () => {
    const view = { x: 40, y: 20, s: 1 };
    const next = zoomAt(view, 300, 200, 1.5);
    const worldBefore = { x: (300 - view.x) / view.s, y: (200 - view.y) / view.s };
    const worldAfter = { x: (300 - next.x) / next.s, y: (200 - next.y) / next.s };
    expect(worldAfter.x).toBeCloseTo(worldBefore.x);
    expect(worldAfter.y).toBeCloseTo(worldBefore.y);
    expect(zoomAt(view, 0, 0, 1)).toBe(view);
  });

  it("nodesBounds incluye el tamaño del nodo", () => {
    const b = nodesBounds([{ position: { x: 10, y: 20 } }, { position: { x: 400, y: 300 } }]);
    expect(b).toEqual({ x: 10, y: 20, w: 390 + NODE_W, h: 280 + NODE_H });
    expect(nodesBounds([])).toBeNull();
  });

  it("fitRect encuadra centrado y respeta el zoom máximo y los insets", () => {
    const rect = { x: 0, y: 0, w: 200, h: 100 };
    const v = fitRect(rect, { w: 1000, h: 600 }, { padding: 0 });
    expect(v.s).toBe(1);
    expect(v.x + (rect.w / 2) * v.s).toBeCloseTo(500);
    const inset = fitRect(rect, { w: 1000, h: 600 }, { padding: 0, insets: { right: 400 } });
    expect(inset.x + (rect.w / 2) * inset.s).toBeCloseTo(300);
    const big = fitRect({ x: 0, y: 0, w: 4000, h: 2000 }, { w: 1000, h: 600 }, { padding: 0 });
    expect(big.s).toBeCloseTo(0.25);
  });

  it("centerOn deja el punto en el centro", () => {
    const v = centerOn({ x: 0, y: 0, s: 0.5 }, 100, 100, { w: 800, h: 600 });
    expect(v.x + 100 * v.s).toBe(400);
    expect(v.y + 100 * v.s).toBe(300);
  });

  it("revealRect no se mueve si el nodo ya es visible y se desplaza lo mínimo si no", () => {
    const view = { x: 0, y: 0, s: 1 };
    const host = { w: 800, h: 600 };
    expect(revealRect(view, { x: 100, y: 100, w: NODE_W, h: NODE_H }, host)).toBe(view);
    const moved = revealRect(view, { x: 700, y: 100, w: NODE_W, h: NODE_H }, host, 0, 16);
    expect(moved.x).toBe(-(700 + NODE_W - (800 - 16)));
    expect(moved.y).toBe(0);
  });

  it("visibleWorldRect y rectsIntersect", () => {
    const r = visibleWorldRect({ x: -100, y: -50, s: 2 }, { w: 400, h: 200 });
    expect(r).toEqual({ x: 50, y: 25, w: 200, h: 100 });
    expect(rectsIntersect(r, { x: 0, y: 0, w: 60, h: 30 })).toBe(true);
    expect(rectsIntersect(r, { x: 300, y: 0, w: 10, h: 10 })).toBe(false);
    expect(rectFromPoints(10, 10, 0, 0)).toEqual({ x: 0, y: 0, w: 10, h: 10 });
  });

  it("detailLevel aplica zoom semántico", () => {
    expect(detailLevel(0.3)).toBe("overview");
    expect(detailLevel(1)).toBe("normal");
    expect(detailLevel(1.5)).toBe("detail");
  });

  it("wheelIntent: pinch/ctrl y rueda hacen zoom, trackpad hace pan", () => {
    expect(wheel({ deltaY: -10, ctrlKey: true })).toMatchObject({ kind: "zoom" });
    const pinch = wheel({ deltaY: -10, ctrlKey: true });
    expect(pinch.kind === "zoom" && pinch.factor > 1).toBe(true);
    const mouse = wheel({ deltaY: 100 });
    expect(mouse.kind === "zoom" && mouse.factor < 1).toBe(true);
    expect(wheel({ deltaY: 3, deltaMode: 1 })).toMatchObject({ kind: "zoom" });
    expect(wheel({ deltaX: 4.5, deltaY: 12.25 })).toEqual({ kind: "pan", dx: -4.5, dy: -12.25 });
    expect(wheel({ deltaY: 100, shiftKey: true })).toEqual({ kind: "pan", dx: -100, dy: 0 });
  });

  it("persiste el viewport por usuario y workflow", () => {
    const key = viewportStorageKey("org:user", "wf-1");
    expect(loadViewport(key)).toBeNull();
    saveViewport(key, { x: 10.4, y: -3.6, s: 0.8123 });
    expect(loadViewport(key)).toEqual({ x: 10, y: -4, s: 0.812 });
    expect(loadViewport(viewportStorageKey("org:user", "wf-2"))).toBeNull();
    window.localStorage.setItem(key, "{bad");
    expect(loadViewport(key)).toBeNull();
  });
});
