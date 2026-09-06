/**
 * Observabilidad del frontend (FASE 14).
 * Captura errores no controlados y correlaciona con trace ids del backend.
 * No se envían secrets ni contenido sensible en telemetry.
 */
import { ApiError, isApiError } from "./errors";

type ReportedError = {
  kind: "error" | "unhandledrejection" | "api";
  message: string;
  traceId: string | null;
  status?: number;
  url?: string;
  at: string;
};

const reporters: ((entry: ReportedError) => void)[] = [];

export function onFrontendError(reporter: (entry: ReportedError) => void) {
  reporters.push(reporter);
  return () => {
    const i = reporters.indexOf(reporter);
    if (i >= 0) reporters.splice(i, 1);
  };
}

function report(entry: ReportedError) {
  for (const fn of reporters) {
    try {
      fn(entry);
    } catch {
      // nunca romper el flujo por telemetry
    }
  }
}

function describeError(err: unknown): { message: string; traceId: string | null; status?: number } {
  if (isApiError(err)) {
    return { message: err.message, traceId: err.traceId, status: err.status };
  }
  if (err instanceof Error) {
    return { message: err.message, traceId: null };
  }
  return { message: String(err), traceId: null };
}

/** Registra los handlers globales (llamar una vez desde main.tsx). */
export function initFrontendObservability() {
  window.addEventListener("error", (event) => {
    const { message, traceId, status } = describeError(event.error);
    report({ kind: "error", message, traceId, status, url: window.location.href, at: new Date().toISOString() });
  });
  window.addEventListener("unhandledrejection", (event) => {
    const { message, traceId, status } = describeError(event.reason);
    report({ kind: "unhandledrejection", message, traceId, status, url: window.location.href, at: new Date().toISOString() });
  });
}

/** Reporta un error capturado en componente (ErrorBoundary). */
export function reportComponentError(err: unknown) {
  const { message, traceId, status } = describeError(err);
  report({ kind: "error", message, traceId, status, url: window.location.href, at: new Date().toISOString() });
}

/** Console-only reporter por defecto. */
onFrontendError((entry) => {
  console.error("[zent-frontend]", entry.kind, entry.message, entry.traceId ? `trace=${entry.traceId}` : "");
});

export type { ReportedError };
export { ApiError };