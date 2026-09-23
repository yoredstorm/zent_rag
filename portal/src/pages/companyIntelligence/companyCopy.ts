/**
 * Textos y etiquetas de Company Intelligence Studio.
 *
 * Los estados del grafo (§22) se muestran SIEMPRE con texto además del color:
 * un badge nunca depende sólo de la tonalidad.
 */
import type { Tone } from "../../components/ui";

export const COPY = {
  subtitle:
    "Cómo funciona la empresa: qué depende de qué, qué fuentes son confiables y qué conocimiento falta.",
  empty:
    "Todavía no hay entidades en el Company Graph. Ejecutá descubrimiento o confirmá candidatos.",
  emptyMap:
    "Elegí una entidad para explorar su vecindad. No se renderiza el grafo completo.",
  emptySearch: "Sin resultados para el filtro aplicado.",
  loadMore: "Expandir más",
  askPlaceholder: "¿Qué procesos dependen de este sistema?",
};

/** Etiqueta legible por estado de entidad o relación (§22). */
export const STATUS_LABELS: Record<string, string> = {
  discovered: "Descubierto",
  supported: "Con respaldo",
  suggested: "Sugerido",
  validated: "Validado",
  confirmed: "Confirmado",
  auto_confirmed: "Auto-confirmado",
  contradicted: "Contradicho",
  stale: "Obsoleto",
  deprecated: "Deprecado",
  rejected: "Rechazado",
};

export const STATUS_TONES: Record<string, Tone> = {
  discovered: "neutral",
  supported: "info",
  suggested: "info",
  validated: "accent",
  confirmed: "ok",
  auto_confirmed: "ok",
  contradicted: "danger",
  stale: "warn",
  deprecated: "neutral",
  rejected: "danger",
};

export function statusLabelFor(status: string | null | undefined): string {
  if (!status) return "Sin estado";
  return STATUS_LABELS[status] || status;
}

export function statusToneFor(status: string | null | undefined): Tone {
  if (!status) return "neutral";
  return STATUS_TONES[status] || "neutral";
}

/** Etiqueta por tipo de entidad del grafo. */
export const ENTITY_TYPE_LABELS: Record<string, string> = {
  organization: "Organización",
  domain: "Dominio",
  concept: "Concepto",
  term: "Término",
  process: "Proceso",
  policy: "Política",
  rule: "Regla",
  system: "Sistema",
  service: "Servicio",
  database: "Base de datos",
  dataset: "Dataset",
  table: "Tabla",
  field: "Campo",
  api: "API",
  knowledge_source: "Fuente de conocimiento",
  document: "Documento",
  agent: "Agente",
  workflow: "Workflow",
  tool: "Herramienta",
  event: "Evento",
  metric: "Métrica",
  kpi: "KPI",
  person: "Persona",
  role: "Rol",
  team: "Equipo",
  claim: "Claim",
  memory: "Memoria",
  decision: "Decisión",
  finding: "Hallazgo",
  experiment: "Experimento",
  recommendation: "Recomendación",
};

export function entityTypeLabel(entityType: string | null | undefined): string {
  if (!entityType) return "Entidad";
  return ENTITY_TYPE_LABELS[entityType] || entityType;
}

/** Grupos con los que el backend agrupa vecinos. */
export const GROUP_LABELS: Record<string, string> = {
  concepts: "Conceptos",
  systems: "Sistemas",
  data: "Datos",
  automation: "Automatización",
  knowledge: "Conocimiento",
  rules: "Reglas",
  institutional: "Institucional",
  processes: "Procesos",
  workflows: "Workflows",
  agents: "Agentes",
  events: "Eventos",
  other: "Otros",
};

export function groupLabel(group: string): string {
  return GROUP_LABELS[group] || group;
}

export const GAP_LABELS: Record<string, string> = {
  undocumented_step: "Paso sin documentar",
  documented_but_unobserved: "Documentado pero no observado",
  no_authoritative_definition: "Sin fuente autoritativa",
  missing_technical_mapping: "Sin mapeo técnico",
  contradictory_definition: "Definición contradictoria",
  ambiguous_entity: "Entidad ambigua",
  missing_process_owner: "Proceso sin responsable",
  stale_relationship: "Relación obsoleta",
};

export function gapLabel(gapKind: string | null | undefined): string {
  if (!gapKind) return "Hueco";
  return GAP_LABELS[gapKind] || gapKind;
}

export const CHANGE_LABELS: Record<string, string> = {
  entity_discovered: "Entidad descubierta",
  entity_updated: "Entidad actualizada",
  entity_deprecated: "Entidad deprecada",
  candidate_entity: "Candidato de entidad",
  candidate_relationship: "Candidato de relación",
  candidate_mapping: "Candidato de mapeo",
  candidate_process: "Candidato de proceso",
  candidate_knowledge_gap: "Candidato de hueco",
  candidate_source_authority: "Candidato de autoridad",
  candidate_term: "Término observado",
  candidate_temporal: "Cambio temporal",
  candidate_mapping_entity: "Candidato",
};

export function changeLabel(kind: string | null | undefined): string {
  if (!kind) return "Cambio";
  return CHANGE_LABELS[kind] || kind;
}

export const INTENT_LABELS: Record<string, string> = {
  entity_lookup: "Identificación",
  representation: "Representación técnica",
  process_of: "Proceso",
  dependency: "Dependencias",
  impact: "Impacto",
  source_of_truth: "Fuente de verdad",
  knowledge_gaps: "Conocimiento faltante",
  changes: "Cambios",
  learned: "Aprendizaje",
  knowledge: "Documentos",
};

export const AUTHORITY_LABELS: Record<string, string> = {
  authoritative: "Autoritativa",
  primary: "Primaria",
  secondary: "Secundaria",
  informational: "Informativa",
  untrusted: "No confiable",
};

export function authorityLabel(level: string | null | undefined): string {
  if (!level) return "Sin autoridad";
  return AUTHORITY_LABELS[level] || level;
}

/** Sufijo honesto sobre la certeza de un camino (§11). */
export function certaintyNote(certainty: string): string {
  return certainty === "will"
    ? "Camino confirmado"
    : "Camino con relaciones no confirmadas: impacto potencial";
}
