// =============================================================================
// mapInsights — derivaciones puras del Knowledge Map
// =============================================================================
// Layout determinista, LOD y explicaciones. Nada se inventa: cada número sale
// del modelo canónico o del detalle del objeto.
// =============================================================================
import type {
  KnowledgeDomain,
  KnowledgeObjectDetail,
} from "../../lib/knowledgeModel";

export type MapLevel = "domains" | "topics" | "objects" | "entity";

export const LEVEL_COPY: Record<MapLevel, { label: string; hint: string }> = {
  domains: {
    label: "Dominios",
    hint: "Las áreas que ZENT ha aprendido. El tamaño refleja cuánto conocimiento contienen.",
  },
  topics: {
    label: "Temas",
    hint: "Tipos de conocimiento dentro del dominio (conceptos, reglas, relaciones...).",
  },
  objects: {
    label: "Conceptos y entidades",
    hint: "Objetos de conocimiento reales, con sus relaciones dentro del tema.",
  },
  entity: {
    label: "Entidad",
    hint: "La entidad enfocada y su vecindario directo de relaciones.",
  },
};

const GOLDEN_ANGLE = 2.399963229728653;

export interface MapNode {
  id: string;
  label: string;
  sublabel?: string;
  size: number;
  x: number;
  y: number;
  tone: "accent" | "info" | "muted" | "warn" | "ok";
  meta?: Record<string, unknown>;
}

export interface MapEdge {
  id: string;
  source: string;
  target: string;
  label: string;
}

export interface MapLayout {
  nodes: MapNode[];
  edges: MapEdge[];
}

function spiral(count: number, radius: number): Array<{ x: number; y: number }> {
  return Array.from({ length: count }, (_, index) => {
    const t = count <= 1 ? 0 : index / (count - 1);
    const angle = index * GOLDEN_ANGLE - Math.PI / 2;
    const r = 5 + Math.sqrt(t) * radius;
    return {
      x: 50 + Math.cos(angle) * r,
      y: 31 + Math.sin(angle) * r * 0.62,
    };
  });
}

/** Nivel 1: clusters por dominio. Tamaño proporcional a objetos reales. */
export function layoutDomains(domains: KnowledgeDomain[]): MapLayout {
  const visible = domains.filter((domain) => domain.objects > 0).slice(0, 24);
  const max = Math.max(1, ...visible.map((domain) => domain.objects));
  const positions = spiral(visible.length, 38);
  const nodes: MapNode[] = visible.map((domain, index) => {
    const ratio = domain.objects / max;
    const conflicts = domain.conflicts ?? 0;
    return {
      id: `domain:${domain.name}`,
      label: domain.name,
      sublabel: `${domain.objects.toLocaleString("es-PE")} objetos`,
      size: 2.4 + Math.sqrt(ratio) * 4.2,
      x: positions[index].x,
      y: positions[index].y,
      tone: conflicts > 0 ? "warn" : domain.verified > 0 ? "accent" : "muted",
      meta: {
        objects: domain.objects,
        verified: domain.verified,
        edges: domain.edges ?? 0,
        conflicts,
        sources: domain.sources,
        last_updated: domain.last_updated ?? null,
        avg_confidence: domain.avg_confidence,
      },
    };
  });
  return { nodes, edges: [] };
}

/** Nivel 2: temas del dominio (by_type real). */
export function layoutTopics(domain: KnowledgeDomain | null): MapLayout {
  const topics = domain?.by_type ?? [];
  if (!domain || topics.length === 0) return { nodes: [], edges: [] };
  const max = Math.max(1, ...topics.map((topic) => topic.total));
  const positions = spiral(topics.length, 30);
  const centerId = `domain:${domain.name}`;
  const nodes: MapNode[] = [
    {
      id: centerId,
      label: domain.name,
      sublabel: `${domain.objects.toLocaleString("es-PE")} objetos`,
      size: 5.4,
      x: 50,
      y: 31,
      tone: "accent",
    },
    ...topics.slice(0, 18).map((topic, index) => ({
      id: `topic:${domain.name}:${topic.type}`,
      label: topicLabel(topic.type),
      sublabel: `${topic.total.toLocaleString("es-PE")} objetos`,
      size: 2.2 + Math.sqrt(topic.total / max) * 3.4,
      x: positions[index].x,
      y: positions[index].y,
      tone: "info" as const,
      meta: { total: topic.total, verified: topic.verified, type: topic.type },
    })),
  ];
  const edges: MapEdge[] = topics.slice(0, 18).map((topic) => ({
    id: `edge:${centerId}:${topic.type}`,
    source: centerId,
    target: `topic:${domain.name}:${topic.type}`,
    label: "contiene",
  }));
  return { nodes, edges };
}

const TOPIC_LABELS: Record<string, string> = {
  entity: "Entidades",
  concept: "Conceptos",
  attribute: "Atributos",
  relationship: "Relaciones",
  business_rule: "Reglas",
  metric: "Métricas",
  kpi: "KPIs",
  process: "Procesos",
  term: "Términos",
  synonym: "Sinónimos",
  event: "Eventos",
  constraint: "Restricciones",
  verified_query: "Consultas verificadas",
  domain: "Subdominios",
};

export function topicLabel(type: string): string {
  return TOPIC_LABELS[type] ?? type;
}

/** Nivel 3/4: objetos y su vecindario, a partir del grafo real del backend. */
export function layoutGraph(
  payload: {
    nodes: Array<{
      id: string;
      type: string;
      name: string;
      status: string;
      confidence: number | null;
      evidence_count: number;
      degree: number;
    }>;
    edges: Array<{
      id: string;
      source: string;
      target: string;
      predicate: string;
      confidence: number;
    }>;
    focus_id?: string | null;
  } | null,
  limit = 70
): MapLayout {
  if (!payload) return { nodes: [], edges: [] };
  const sorted = [...payload.nodes]
    .sort((a, b) => b.degree - a.degree)
    .slice(0, limit);
  const focusId = payload.focus_id ?? sorted[0]?.id ?? null;
  const positions = spiral(sorted.length, 38);
  const nodes: MapNode[] = sorted.map((node, index) => {
    const isFocus = node.id === focusId;
    const position = isFocus
      ? { x: 50, y: 31 }
      : positions[index];
    return {
      id: node.id,
      label: node.name,
      sublabel: `${node.degree} conexiones`,
      size: isFocus ? 4.6 : 1.6 + Math.min(3.4, Math.sqrt(node.degree + 1) * 0.7),
      x: position.x,
      y: position.y,
      tone: isFocus
        ? "accent"
        : node.status === "conflicted"
          ? "warn"
          : node.status === "verified"
            ? "ok"
            : "info",
      meta: {
        type: node.type,
        status: node.status,
        confidence: node.confidence,
        evidence_count: node.evidence_count,
        degree: node.degree,
        focus: isFocus,
      },
    };
  });
  const nodeIds = new Set(nodes.map((node) => node.id));
  const edges: MapEdge[] = payload.edges
    .filter((edge) => nodeIds.has(edge.source) && nodeIds.has(edge.target))
    .map((edge) => ({
      id: edge.id,
      source: edge.source,
      target: edge.target,
      label: edge.predicate,
    }));
  return { nodes, edges };
}

// ---------------------------------------------------------------------------
// Knowledge strength explicable
// ---------------------------------------------------------------------------

export interface StrengthComponent {
  key: string;
  label: string;
  value: number | null;
  display: string;
  hint: string;
}

export interface KnowledgeStrength {
  score: number | null;
  label: string;
  components: StrengthComponent[];
  explanation: string;
}

const COMPONENT_LABELS: Record<string, { label: string; hint: string }> = {
  evidence_strength: {
    label: "Evidencia",
    hint: "Fuerza media de las evidencias localizables de este conocimiento.",
  },
  source_reliability: {
    label: "Fiabilidad de fuentes",
    hint: "Autoridad media de las fuentes que respaldan este conocimiento.",
  },
  corroboration: {
    label: "Corroboración",
    hint: "Cuánta evidencia independiente respalda el conocimiento (3 o más satura).",
  },
  semantic_certainty: {
    label: "Certeza semántica",
    hint: "Qué tan inequívoca es la interpretación (método de extracción).",
  },
  freshness: {
    label: "Vigencia",
    hint: "Qué tan reciente es la evidencia respecto a la fuente.",
  },
};

function pct(value: number): string {
  return `${Math.round(value * 100)}%`;
}

/**
 * Agrega los componentes reales de `confidence_detail` de las afirmaciones del
 * objeto. Si no hay detalle, se explica en vez de inventar un score.
 */
export function deriveKnowledgeStrength(
  detail: KnowledgeObjectDetail | null,
  options: { conflicts?: number } = {}
): KnowledgeStrength {
  if (!detail) {
    return {
      score: null,
      label: "Sin datos",
      components: [],
      explanation: "Selecciona un objeto para ver su respaldo real.",
    };
  }
  const sums: Record<string, { total: number; count: number }> = {};
  for (const assertion of detail.assertions) {
    const components = (assertion.confidence_detail?.components ?? {}) as Record<
      string,
      unknown
    >;
    for (const key of Object.keys(COMPONENT_LABELS)) {
      const value = Number(components[key]);
      if (Number.isFinite(value)) {
        const bucket = sums[key] ?? { total: 0, count: 0 };
        bucket.total += value;
        bucket.count += 1;
        sums[key] = bucket;
      }
    }
  }
  const components: StrengthComponent[] = Object.entries(COMPONENT_LABELS).map(
    ([key, meta]) => {
      const bucket = sums[key];
      const value = bucket && bucket.count > 0 ? bucket.total / bucket.count : null;
      return {
        key,
        label: meta.label,
        hint: meta.hint,
        value,
        display: value != null ? pct(value) : "No medido",
      };
    }
  );
  const independentSources = new Set(
    detail.evidence.map((evidence) => evidence.source_id).filter(Boolean)
  ).size;
  components.push({
    key: "independent_sources",
    label: "Fuentes independientes",
    hint: "Fuentes distintas que aportan evidencia a este conocimiento.",
    value: independentSources > 0 ? Math.min(1, independentSources / 4) : null,
    display: String(independentSources),
  });
  components.push({
    key: "consistency",
    label: "Consistencia",
    hint: "Conflictos abiertos detectados sobre este conocimiento.",
    value: options.conflicts != null ? (options.conflicts > 0 ? 0 : 1) : null,
    display:
      options.conflicts == null
        ? "No medido"
        : options.conflicts === 0
          ? "Sin conflictos"
          : `${options.conflicts} conflicto(s)`,
  });
  components.push({
    key: "entity_resolution",
    label: "Resolución de entidad",
    hint: "Cómo se identifica este objeto: canónico, fusionado o inferido.",
    value: null,
    display: detail.object.provenance || detail.object.status,
  });

  return {
    score: detail.object.confidence,
    label: detail.object.confidence_label || "sin etiqueta",
    components,
    explanation:
      "Knowledge strength combina evidencia, fiabilidad de fuentes, corroboración, certeza semántica y vigencia con la fórmula del backend: producto ponderado de componentes, con techo 0.6 sin evidencia y piso 0.9 al verificar con evidencia.",
  };
}

// ---------------------------------------------------------------------------
// Evidence path: ¿cómo sabe ZENT esto?
// ---------------------------------------------------------------------------

export interface EvidenceStep {
  id: string;
  kind: "object" | "assertion" | "evidence" | "source" | "page";
  label: string;
  detail?: string;
  sourceId?: string | null;
  page?: number | null;
}

export function buildEvidencePath(
  detail: KnowledgeObjectDetail | null,
  sourceNames: Record<string, string> = {}
): EvidenceStep[] {
  if (!detail) return [];
  const steps: EvidenceStep[] = [
    {
      id: "object",
      kind: "object",
      label: detail.object.display_name || detail.object.name,
      detail: detail.object.description ?? undefined,
    },
  ];
  const assertion = detail.assertions[0];
  if (assertion) {
    steps.push({
      id: `assertion:${assertion.id}`,
      kind: "assertion",
      label: `${assertion.subject_label} ${assertion.predicate} ${
        assertion.object_value ?? assertion.object_id ?? ""
      }`.trim(),
      detail: `${assertion.method} · confianza ${pct(assertion.confidence)}`,
      sourceId: assertion.source_id,
    });
  }
  const evidence = detail.evidence[0];
  if (evidence) {
    steps.push({
      id: `evidence:${evidence.id}`,
      kind: "evidence",
      label: evidence.excerpt || "Evidencia localizable",
      detail: evidence.evidence_type,
      sourceId: evidence.source_id,
      page: evidence.page,
    });
    if (evidence.source_id) {
      steps.push({
        id: `source:${evidence.source_id}`,
        kind: "source",
        label:
          sourceNames[evidence.source_id] ||
          `Fuente ${evidence.source_id.slice(0, 8)}`,
        sourceId: evidence.source_id,
      });
    }
    if (evidence.page != null) {
      steps.push({
        id: `page:${evidence.page}`,
        kind: "page",
        label: `Página ${evidence.page}`,
        detail: evidence.section_path.join(" › ") || undefined,
        sourceId: evidence.source_id,
        page: evidence.page,
      });
    }
  }
  return steps;
}

// ---------------------------------------------------------------------------
// Timeline: versiones + vigencia temporal
// ---------------------------------------------------------------------------

export interface TimelineEntry {
  id: string;
  at: string | null;
  kind: "version" | "temporal";
  title: string;
  detail?: string;
}

export function buildTimeline(detail: KnowledgeObjectDetail | null): TimelineEntry[] {
  if (!detail) return [];
  const entries: TimelineEntry[] = detail.versions.map((version) => ({
    id: `version:${version.version}:${version.created_at}`,
    at: version.created_at,
    kind: "version",
    title: `v${version.version} · ${version.change_kind}`,
    detail: version.reason ?? undefined,
  }));
  for (const assertion of detail.assertions) {
    const from = assertion.valid_from;
    const to = assertion.valid_to;
    if (!from && !to) continue;
    entries.push({
      id: `temporal:${assertion.id}`,
      at: from ?? to ?? null,
      kind: "temporal",
      title: assertion.object_value ?? assertion.predicate,
      detail:
        from || to
          ? `Vigencia: ${from ? from.slice(0, 10) : "—"} a ${
              to ? to.slice(0, 10) : "hoy"
            }`
          : undefined,
    });
  }
  return entries.sort((a, b) => {
    const ta = a.at ? Date.parse(a.at) : 0;
    const tb = b.at ? Date.parse(b.at) : 0;
    return tb - ta;
  });
}

// ---------------------------------------------------------------------------
// Coverage real por dominio
// ---------------------------------------------------------------------------

export function domainCoverage(domain: KnowledgeDomain): {
  pct: number;
  label: string;
  formula: string;
} {
  const pctValue =
    domain.objects > 0 ? Math.round((domain.verified / domain.objects) * 100) : 0;
  return {
    pct: pctValue,
    label: `${pctValue}% verificado`,
    formula:
      "objetos verificados / objetos de negocio del dominio. Los objetos de soporte (tablas, columnas, documentos) no cuentan.",
  };
}
