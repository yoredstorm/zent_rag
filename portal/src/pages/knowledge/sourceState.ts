export type SourceReadinessKey =
  | "received"
  | "processing"
  | "ready"
  | "attention"
  | "unknown";

export type SourceReadiness = {
  key: SourceReadinessKey;
  label: string;
  detail: string;
  tone: "neutral" | "warn" | "ok" | "danger";
};

const STATES: Record<SourceReadinessKey, Omit<SourceReadiness, "key">> = {
  received: {
    label: "Recibido",
    detail: "La fuente se registró y espera el inicio del procesamiento.",
    tone: "neutral",
  },
  processing: {
    label: "Procesando",
    detail: "La ingesta o el indexado están en curso; todavía no está lista para citar.",
    tone: "warn",
  },
  ready: {
    label: "Listo para consultar",
    detail: "La fuente terminó el indexado y puede recuperarse con citas.",
    tone: "ok",
  },
  attention: {
    label: "Necesita atención",
    detail: "La fuente falló; abre el detalle para ver el error y la acción disponible.",
    tone: "danger",
  },
  unknown: {
    label: "No medido",
    detail: "No hay una señal de disponibilidad verificable para esta fuente.",
    tone: "neutral",
  },
};

export function sourceReadiness(status: string): SourceReadiness {
  if (status === "indexed") return { key: "ready", ...STATES.ready };
  if (status === "error") return { key: "attention", ...STATES.attention };
  if (["created", "connected"].includes(status)) {
    return { key: "received", ...STATES.received };
  }
  if (["discovering", "profiled", "ready", "ingesting"].includes(status)) {
    return { key: "processing", ...STATES.processing };
  }
  return { key: "unknown", ...STATES.unknown };
}
