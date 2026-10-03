// =============================================================================
// Lenguaje humano del Knowledge OS
// =============================================================================
// El flujo principal nunca habla de chunks, embeddings ni indexado. Esos
// términos viven en la sección Avanzado. Aquí se traduce el estado real del
// backend a frases que describen aprendizaje, conexión y comprensión.
// =============================================================================
import type { HealthDimension, KnowledgeHealth } from "./knowledgeModel";
import type { LearningEvent } from "./knowledgeLearning";

export const HUMAN_STAGE_LABELS: Record<string, string> = {
  connecting: "Conectando con la fuente",
  discovering_schema: "Leyendo la estructura",
  profiling: "Entendiendo los datos",
  detecting_entities: "Descubriendo entidades",
  analyzing_fields: "Comprendiendo campos",
  detecting_relationships: "Conectando relaciones",
  llm_reasoning: "Razonando",
  generating_questions: "Preparando preguntas",
  awaiting_validation: "Esperando tu validación",
  chunking: "Organizando el contenido",
  embedding: "Comprendiendo significados",
  indexing: "Preparando para responder",
  evaluating: "Verificando lo aprendido",
  scoring: "Midiendo la salud del conocimiento",
  ready: "Conocimiento listo",
};

export function humanStageLabel(stage: string | null | undefined): string {
  if (!stage) return "";
  return HUMAN_STAGE_LABELS[stage] || stage;
}

export const CATEGORY_VERBS: Record<string, string> = {
  discovery: "descubrió",
  ai: "comprendió",
  validation: "verificó",
  indexing: "organizó",
  system: "registró",
};

const COUNT_LABELS: Array<[string, string]> = [
  ["entities", "entidades"],
  ["concepts", "conceptos"],
  ["facts", "hechos"],
  ["relationships", "relaciones"],
  ["rules", "reglas"],
  ["metrics", "métricas"],
  ["evidence", "evidencias"],
  ["terms", "términos"],
  ["tables", "tablas"],
  ["fields", "campos"],
  ["carrier_codes", "Carrier Codes"],
];

const TECHNICAL_RE =
  /chunk|embedding|vector|index(ando|ado)|qdrant|token|batch|stage|run\b/i;

/**
 * Titular humano de un evento de aprendizaje real. Usa el mensaje del backend
 * cuando ya es humano; si trae conteos reales en el payload, los compone.
 */
export function learningEventHeadline(event: LearningEvent): string {
  const payload = event.payload ?? {};
  const parts = COUNT_LABELS.filter(([key]) => Number(payload[key]) > 0).map(
    ([key, label]) => `${Number(payload[key]).toLocaleString("es-PE")} ${label}`
  );
  const verb = CATEGORY_VERBS[event.category] || "registró";
  if (parts.length > 0) return `ZENT ${verb} ${parts.join(" · ")}`;
  const message = (event.message || "").trim();
  if (message && !TECHNICAL_RE.test(message)) return message;
  return `ZENT ${verb} conocimiento nuevo`;
}

export const KNOWLEDGE_EVENT_LABELS: Record<string, string> = {
  new_entity: "Nueva entidad",
  new_rule: "Nueva regla",
  rule_changed: "Regla actualizada",
  conflict_detected: "Posible conflicto",
  source_superseded: "Fuente reemplazada",
  knowledge_gap_detected: "Vacío de conocimiento",
  high_impact_change: "Cambio de alto impacto",
};

export function knowledgeEventLabel(eventType: string): string {
  const key = eventType.replace(/^knowledge\./, "");
  return KNOWLEDGE_EVENT_LABELS[key] || eventType;
}

/** Traduce la salud a significado humano. Nunca solo el número. */
export function interpretHealth(health: KnowledgeHealth): string {
  const overall = health.overall;
  if (overall == null || health.measured_dimensions === 0) {
    return "Todavía no hay suficiente conocimiento medido para evaluar la salud.";
  }
  const unmeasured = health.total_dimensions - health.measured_dimensions;
  const prefix =
    overall >= 85
      ? "Tu Knowledge OS está saludable."
      : overall >= 65
        ? "Tu Knowledge OS está estable, con puntos por reforzar."
        : "Tu Knowledge OS necesita atención.";
  const weak = health.dimensions
    .filter((d) => d.measured && d.score != null && d.score < 60)
    .map((d) => d.label.toLowerCase());
  const parts: string[] = [];
  if (weak.length > 0) parts.push(`Conviene reforzar ${weak.slice(0, 2).join(" y ")}.`);
  if (unmeasured > 0) {
    parts.push(`${unmeasured} dimensión(es) aún sin datos para medir.`);
  }
  return parts.length > 0 ? `${prefix} ${parts.join(" ")}` : prefix;
}

/** Frase corta para una dimensión de salud. */
export function dimensionSummary(dimension: HealthDimension): string {
  if (!dimension.measured || dimension.score == null) return "No medido";
  if (dimension.score >= 85) return "Sólido";
  if (dimension.score >= 65) return "Aceptable";
  if (dimension.score >= 40) return "Débil";
  return "Crítico";
}
