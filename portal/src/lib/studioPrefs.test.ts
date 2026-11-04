import { describe, expect, it } from "vitest";
import { canvasNodeKind, canvasNodeKindMeta } from "./canvasNodeKind";
import { searchGraphNodes } from "./graphSearch";
import { MAX_RECENTS, loadFavorites, loadRecents, pushRecent, toggleFavorite } from "./nodeCatalogPrefs";
import {
  DEFAULT_PREFS,
  INSPECTOR_WIDTH,
  clampInspectorWidth,
  clampSimulatorHeight,
  inspectorDocked,
  loadStudioPrefs,
  panelMode,
  panelsExclusive,
  saveStudioPrefs,
} from "./studioLayout";
import { makeNode } from "./workflowGraph";

describe("studioLayout", () => {
  it("modo de paneles por ancho y exclusividad en pantallas reducidas", () => {
    expect(panelMode(1920)).toBe("wide");
    expect(panelMode(1280)).toBe("wide");
    expect(panelMode(1100)).toBe("compact");
    expect(panelMode(800)).toBe("mobile");
    expect(inspectorDocked("wide")).toBe(true);
    expect(inspectorDocked("compact")).toBe(false);
    expect(panelsExclusive("wide")).toBe(false);
    expect(panelsExclusive("compact")).toBe(true);
  });

  it("limita inspector y simulador para que el lienzo domine", () => {
    expect(INSPECTOR_WIDTH.initial).toBeGreaterThanOrEqual(360);
    expect(INSPECTOR_WIDTH.initial).toBeLessThanOrEqual(440);
    expect(clampInspectorWidth(100)).toBe(INSPECTOR_WIDTH.min);
    expect(clampInspectorWidth(900, 1000)).toBe(500);
    expect(clampSimulatorHeight(50)).toBe(180);
    expect(clampSimulatorHeight(900, 800)).toBe(560);
  });

  it("persiste preferencias y tolera datos corruptos", () => {
    expect(loadStudioPrefs()).toEqual(DEFAULT_PREFS);
    saveStudioPrefs({ inspectorWidth: 420, simulatorHeight: 260, minimap: false });
    expect(loadStudioPrefs()).toEqual({ inspectorWidth: 420, simulatorHeight: 260, minimap: false });
    window.localStorage.setItem("zent.wf.studio.prefs.v1", "nope");
    expect(loadStudioPrefs()).toEqual(DEFAULT_PREFS);
  });
});

describe("nodeCatalogPrefs", () => {
  it("favoritos alternan y recientes se ordenan sin duplicados", () => {
    expect(loadFavorites()).toEqual([]);
    expect(toggleFavorite("llm")).toEqual(["llm"]);
    expect(toggleFavorite("notify")).toEqual(["llm", "notify"]);
    expect(toggleFavorite("llm")).toEqual(["notify"]);
    pushRecent("a");
    pushRecent("b");
    expect(pushRecent("a")).toEqual(["a", "b"]);
    for (let i = 0; i < 10; i += 1) pushRecent(`t${i}`);
    expect(loadRecents()).toHaveLength(MAX_RECENTS);
  });
});

describe("searchGraphNodes", () => {
  const nodes = [
    { ...makeNode("notify"), id: "n-aviso", label: "Avisar al cliente" },
    { ...makeNode("condition"), id: "n-stock", label: "¿Hay stock?" },
    { ...makeNode("human_approval"), id: "approve-pay", label: "Aprobar pago" },
  ];

  it("busca por nombre, tipo e id sin acentos", () => {
    expect(searchGraphNodes(nodes, "avisar")[0].node.id).toBe("n-aviso");
    expect(searchGraphNodes(nodes, "condition")[0].node.id).toBe("n-stock");
    expect(searchGraphNodes(nodes, "approve")[0].node.id).toBe("approve-pay");
    expect(searchGraphNodes(nodes, "aprobacion").map((h) => h.node.id)).toContain("approve-pay");
    expect(searchGraphNodes(nodes, "zzz")).toEqual([]);
    expect(searchGraphNodes(nodes, "")).toHaveLength(3);
  });
});

describe("canvasNodeKind", () => {
  it("distingue aprobación de espera y conserva el resto de roles", () => {
    expect(canvasNodeKind(makeNode("human_approval"))).toBe("approval");
    expect(canvasNodeKind(makeNode("condition"))).toBe("decision");
    expect(canvasNodeKind(makeNode("trigger_webhook"))).toBe("trigger");
    expect(canvasNodeKind(makeNode("end"))).toBe("end");
    expect(canvasNodeKindMeta("approval").label).toBe("Aprobación");
    expect(canvasNodeKindMeta("trigger").shape).toContain("rounded-l-2xl");
  });
});
