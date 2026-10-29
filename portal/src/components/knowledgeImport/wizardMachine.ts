// =============================================================================
// P18.1-03 — Máquina explícita del lote de incorporación.
// =============================================================================
// No representa "progreso" decorativo: solo archivos confirmados por el
// backend y el estado durable de la sesión. Las transiciones inválidas se
// ignoran para que una respuesta tardía no retroceda el recorrido.
// =============================================================================

export type WizardBatchPhase =
  | "idle"
  | "transfer"
  | "processing"
  | "partial"
  | "available"
  | "failed"
  | "done";

export type WizardBatchState = {
  phase: WizardBatchPhase;
  total: number;
  confirmed: number;
  failed: number;
  sessionId: string | null;
};

export type WizardBatchEvent =
  | { type: "start"; total: number }
  | { type: "uploaded"; ok: boolean }
  | { type: "session"; sessionId: string }
  | { type: "processing" }
  | { type: "settled"; ready: number; failed: number; total: number }
  | { type: "reset" }
  | { type: "done" };

export const initialWizardBatch: WizardBatchState = {
  phase: "idle",
  total: 0,
  confirmed: 0,
  failed: 0,
  sessionId: null,
};

const TERMINAL: WizardBatchPhase[] = ["partial", "available", "failed", "done"];

export function wizardBatchReducer(
  state: WizardBatchState,
  event: WizardBatchEvent,
): WizardBatchState {
  switch (event.type) {
    case "start":
      if (state.phase === "transfer") return state;
      return {
        phase: "transfer",
        total: Math.max(0, event.total),
        confirmed: 0,
        failed: 0,
        sessionId: null,
      };
    case "uploaded": {
      if (state.phase !== "transfer") return state;
      const confirmed = state.confirmed + (event.ok ? 1 : 0);
      const failed = state.failed + (event.ok ? 0 : 1);
      const finished = confirmed + failed >= state.total;
      return {
        ...state,
        confirmed,
        failed,
        phase: finished ? "processing" : "transfer",
      };
    }
    case "session":
      return { ...state, sessionId: event.sessionId };
    case "processing":
      if (TERMINAL.includes(state.phase) || state.phase === "idle") return state;
      return { ...state, phase: "processing" };
    case "settled": {
      const total = Math.max(0, event.total);
      const ready = Math.max(0, event.ready);
      const failed = Math.max(0, event.failed);
      if (ready > 0 && failed > 0) {
        return { ...state, phase: "partial", total, confirmed: ready, failed };
      }
      if (ready > 0) {
        return { ...state, phase: "available", total, confirmed: ready, failed };
      }
      if (failed > 0) {
        return { ...state, phase: "failed", total, failed };
      }
      return { ...state, phase: "processing", total };
    }
    case "done":
      return { ...state, phase: "done" };
    case "reset":
      return initialWizardBatch;
    default:
      return state;
  }
}

export function canAskBatch(state: WizardBatchState): boolean {
  return (
    Boolean(state.sessionId) &&
    (state.phase === "available" || state.phase === "partial")
  );
}

export function batchProgressLabel(state: WizardBatchState): string {
  if (state.phase === "transfer") {
    return `${state.confirmed + state.failed} de ${state.total} archivos confirmados`;
  }
  if (state.phase === "processing") {
    return "Procesando los archivos recibidos";
  }
  if (state.phase === "partial") {
    return `${state.confirmed} listas, ${state.failed} con problemas`;
  }
  if (state.phase === "available") {
    return `${state.confirmed} disponibles para consultar`;
  }
  if (state.phase === "failed") {
    return "Ninguna fuente quedó disponible";
  }
  return "";
}
