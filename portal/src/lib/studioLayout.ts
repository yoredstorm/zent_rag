/**
 * Reglas de layout del Workflow Studio canvas-first: tamaños de paneles
 * (persistidos por navegador) y cuántos paneles pueden convivir según el
 * ancho disponible. El lienzo siempre tiene prioridad.
 */

export type StudioPrefs = {
  inspectorWidth: number;
  simulatorHeight: number;
  minimap: boolean;
  /** Ancho del panel de resultado dentro del simulador dividido. */
  testResultWidth: number;
};

export const INSPECTOR_WIDTH = { min: 320, max: 640, initial: 400 } as const;
export const SIMULATOR_HEIGHT = { min: 180, initial: 500, maxRatio: 0.7 } as const;
/** Panel derecho del simulador. El izquierdo conserva al menos `TEST_ENTRY_MIN`. */
export const TEST_RESULT_WIDTH = { min: 280, initial: 520 } as const;
const TEST_ENTRY_MIN = 280;
const TEST_RESULT_MAX_RATIO = 0.72;
const TEST_RESULT_UNMEASURED_MAX = 1200;
/** Debajo de este alto la consola dividida no muestra la entrada completa. */
const SIMULATOR_COMFORT_HEIGHT = 400;

const PREFS_KEY = "zent.wf.studio.prefs.v1";

export const DEFAULT_PREFS: StudioPrefs = {
  inspectorWidth: INSPECTOR_WIDTH.initial,
  simulatorHeight: SIMULATOR_HEIGHT.initial,
  minimap: true,
  testResultWidth: TEST_RESULT_WIDTH.initial,
};

export function clamp(value: number, min: number, max: number): number {
  return Math.min(max, Math.max(min, value));
}

export function clampInspectorWidth(width: number, viewportWidth = Infinity): number {
  // Nunca más de la mitad del ancho: el lienzo sigue siendo dominante.
  const max = Math.min(INSPECTOR_WIDTH.max, Math.max(INSPECTOR_WIDTH.min, viewportWidth * 0.5));
  return Math.round(clamp(width, INSPECTOR_WIDTH.min, max));
}

export function clampSimulatorHeight(height: number, availableHeight = Infinity): number {
  const max = Math.max(SIMULATOR_HEIGHT.min, availableHeight * SIMULATOR_HEIGHT.maxRatio);
  return Math.round(clamp(height, SIMULATOR_HEIGHT.min, max));
}

/** Ancho del resultado. Sin medir el contenedor, solo aplica el techo absoluto. */
export function clampTestResultWidth(width: number, containerWidth = Infinity): number {
  const measured = Number.isFinite(containerWidth) && containerWidth > 0;
  const max = measured
    ? Math.max(
        TEST_RESULT_WIDTH.min,
        Math.min(containerWidth * TEST_RESULT_MAX_RATIO, containerWidth - TEST_ENTRY_MIN),
      )
    : TEST_RESULT_UNMEASURED_MAX;
  return Math.round(clamp(width, TEST_RESULT_WIDTH.min, max));
}

export function loadStudioPrefs(): StudioPrefs {
  try {
    const raw = window.localStorage.getItem(PREFS_KEY);
    if (!raw) return { ...DEFAULT_PREFS };
    const parsed = JSON.parse(raw) as Partial<StudioPrefs>;
    const storedHeight =
      typeof parsed.simulatorHeight === "number" ? clampSimulatorHeight(parsed.simulatorHeight) : null;
    return {
      inspectorWidth:
        typeof parsed.inspectorWidth === "number" ? clampInspectorWidth(parsed.inspectorWidth) : DEFAULT_PREFS.inspectorWidth,
      // Migración: el dock antiguo guardaba 320 px. La consola dividida necesita
      // más alto para mostrar modo, mensaje y acciones sin que el footer lo tape.
      simulatorHeight:
        storedHeight !== null && storedHeight >= SIMULATOR_COMFORT_HEIGHT
          ? storedHeight
          : DEFAULT_PREFS.simulatorHeight,
      minimap: typeof parsed.minimap === "boolean" ? parsed.minimap : DEFAULT_PREFS.minimap,
      testResultWidth:
        typeof parsed.testResultWidth === "number"
          ? clampTestResultWidth(parsed.testResultWidth)
          : DEFAULT_PREFS.testResultWidth,
    };
  } catch {
    return { ...DEFAULT_PREFS };
  }
}

export function saveStudioPrefs(prefs: StudioPrefs): void {
  try {
    window.localStorage.setItem(PREFS_KEY, JSON.stringify(prefs));
  } catch {
    // sin persistencia
  }
}

/**
 * - wide (≥ 1280 px): inspector acoplado a la derecha (empuja el lienzo).
 * - compact (1024–1279 px): inspector flotante sobre el lienzo; catálogo e
 *   inspector no conviven.
 * - mobile (< 1024 px): simulador como hoja inferior; inspector flotante.
 */
export type PanelMode = "wide" | "compact" | "mobile";

export function panelMode(viewportWidth: number): PanelMode {
  if (viewportWidth >= 1280) return "wide";
  if (viewportWidth >= 1024) return "compact";
  return "mobile";
}

export function inspectorDocked(mode: PanelMode): boolean {
  return mode === "wide";
}

/** En pantallas reducidas abrir el catálogo cierra el inspector (y viceversa). */
export function panelsExclusive(mode: PanelMode): boolean {
  return mode !== "wide";
}
