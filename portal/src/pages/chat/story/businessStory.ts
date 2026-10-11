// =============================================================================
// Business Story (P7) — el portal TRADUCE; el backend manda reason_code + facts.
// =============================================================================
// Contrato del endpoint: GET /api/v1/executions/agent/{run_id}/story?view=...
// business: {type, status, reason_code, facts} — sin campos técnicos ni CoT.
// technical: steps crudos (contenido truncado).
// =============================================================================
import { api, type Session } from "../../../api";

export type BusinessTone = "ok" | "warn" | "error" | "neutral";

export type BusinessStep = {
  type: string;
  source_type?: string | null;
  status: string;
  reason_code: string;
  facts?: Record<string, unknown>;
  detail?: string;
};

export type BusinessStory = {
  version: string;
  view: string;
  steps: BusinessStep[];
  kind?: string;
  id?: string;
};

export type TranslatedStep = BusinessStep & {
  title: string;
  caption: string;
  tone: BusinessTone;
};

type Copy = { title: string; caption: string; tone: BusinessTone };

const COPY: Record<string, Copy> = {
  EVIDENCE_COMPLETE: {
    title: "Evidencia suficiente",
    caption: "Zent encontró respaldo para todos los aspectos necesarios.",
    tone: "ok",
  },
  EVIDENCE_PARTIAL: {
    title: "Evidencia parcial",
    caption: "Hay respaldo para parte de lo preguntado; se responde con límites.",
    tone: "warn",
  },
  EVIDENCE_INCOMPLETE: {
    title: "Falta evidencia",
    caption: "Se buscó y no alcanza todavía: se puede buscar otra ronda.",
    tone: "warn",
  },
  EVIDENCE_INSUFFICIENT: {
    title: "Sin evidencia suficiente",
    caption: "No hay respaldo en las fuentes para responder con fundamento.",
    tone: "warn",
  },
  EVIDENCE_EVALUATED: {
    title: "Evidencia evaluada",
    caption: "Se midió la evidencia disponible para este run.",
    tone: "neutral",
  },
  ANSWER_APPROVED: {
    title: "Respuesta aprobada",
    caption: "El borrador quedó respaldado por la evidencia.",
    tone: "ok",
  },
  ANSWER_LIMITED: {
    title: "Respuesta con límites",
    caption: "Se responde lo respaldado y se declara lo que falta.",
    tone: "warn",
  },
  ANSWER_REVISION_REQUESTED: {
    title: "Se pidió una revisión",
    caption: "El borrador necesitaba ajustes antes de entregarse.",
    tone: "warn",
  },
  RETRIEVAL_REQUESTED: {
    title: "Se pidió otra búsqueda",
    caption: "El verificador consideró que faltaba evidencia.",
    tone: "warn",
  },
  ANSWER_ABSTAINED: {
    title: "No se respondió",
    caption: "No hubo respaldo suficiente: se prefirió no inventar.",
    tone: "warn",
  },
  ANSWER_UNDETERMINED: {
    title: "No se pudo determinar",
    caption: "Falta una premisa o autoridad para concluir; no se decide en silencio.",
    tone: "warn",
  },
  ANSWER_CONFLICTING: {
    title: "Fuentes contradictorias",
    caption: "Las fuentes se contradicen: no se elige una versión en silencio.",
    tone: "warn",
  },
  RETRIEVAL_UNAVAILABLE: {
    title: "Búsqueda no disponible",
    caption: "El proveedor de búsqueda falló: es un fallo operativo, no ausencia de datos.",
    tone: "error",
  },
  TOOL_EXECUTED: {
    title: "Herramienta ejecutada",
    caption: "Zent consultó una herramienta para obtener datos.",
    tone: "neutral",
  },
  TOOL_FAILED: {
    title: "La herramienta falló",
    caption: "La consulta a la herramienta no pudo completarse.",
    tone: "error",
  },
  AUTHORITY_LOCKED: {
    title: "Decisión asegurada",
    caption: "La respuesta final proviene de la decisión determinista.",
    tone: "ok",
  },
  AUTHORITY_OVERRIDDEN: {
    title: "Se corrigió el texto",
    caption: "El texto contradecía la decisión: se reconstruyó desde la autoridad.",
    tone: "warn",
  },
  CONSISTENCY_VIOLATIONS: {
    title: "Inconsistencias detectadas",
    caption: "El estado del run no cerró consistente; quedó registrado para diagnóstico.",
    tone: "error",
  },
  REQUEST_SATISFIED: {
    title: "Pedido satisfecho",
    caption: "El objetivo del usuario quedó cubierto.",
    tone: "ok",
  },
  REQUEST_NOT_SATISFIED: {
    title: "Pedido aún no cubierto",
    caption: "Todavía falta cubrir parte de lo pedido.",
    tone: "neutral",
  },
  ANSWER_READY: {
    title: "Respuesta lista",
    caption: "La respuesta final quedó disponible.",
    tone: "ok",
  },
  STEP_RECORDED: {
    title: "Paso registrado",
    caption: "Evento del run sin traducción específica.",
    tone: "neutral",
  },
};

const TONE_FALLBACK: Record<string, BusinessTone> = {
  ok: "ok",
  warn: "warn",
  error: "error",
};

export function executionStoryPath(
  ref: { kind: string; id: string },
  view: "business" | "technical" = "business",
): string {
  return `/api/v1/executions/${ref.kind}/${ref.id}/story?view=${view}`;
}

export function translateReasonCode(
  code: string,
  fallbackTone: BusinessTone = "neutral",
): Copy {
  const known = COPY[String(code || "").toUpperCase()];
  if (known) return known;
  if (String(code || "").toUpperCase().startsWith("AUTHORITY_")) {
    return {
      title: "Resolución de autoridad",
      caption: "Zent resolvió quién manda entre las señales del run.",
      tone: TONE_FALLBACK[fallbackTone] ?? "neutral",
    };
  }
  if (String(code || "").toUpperCase().startsWith("DELIVERY_")) {
    return {
      title: "Camino de respuesta",
      caption: "Se eligió cómo entregar la respuesta del run.",
      tone: "neutral",
    };
  }
  return {
    title: String(code || "Paso"),
    caption: "Evento del run.",
    tone: TONE_FALLBACK[fallbackTone] ?? "neutral",
  };
}

export function translateBusinessSteps(steps: BusinessStep[]): TranslatedStep[] {
  return (steps || []).map((step) => {
    const tone: BusinessTone =
      step.status === "error" ? "error" : step.status === "warn" ? "warn" : "neutral";
    const copy = translateReasonCode(step.reason_code, tone);
    return { ...step, ...copy };
  });
}

export async function fetchAgentStory(
  ref: { kind: string; id: string },
  session: Session,
  view: "business" | "technical" = "business",
): Promise<BusinessStory> {
  return api<BusinessStory>(executionStoryPath(ref, view), {
    token: session.token,
    organizationId: session.organizationId,
  });
}
