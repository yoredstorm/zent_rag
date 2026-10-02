// =============================================================================
// Cognitive story — parser del nivel cognitivo del flow (C6).
// =============================================================================
export interface CognitiveStoryStep {
  kind: string;
  phase: string;
  status: string;
  metrics: Record<string, unknown>;
}

export interface CognitiveStory {
  schemaVersion: number;
  normal: CognitiveStoryStep[];
  expanded: Record<string, unknown>;
  raw: Record<string, unknown>;
}

export const COGNITIVE_STEP_LABELS: Record<
  string,
  { title: string; body: (metrics: Record<string, unknown>) => string }
> = {
  cognitive_plan: {
    title: "Planeó la consulta",
    body: (m) => `Complejidad ${String(m.complexity ?? "—")} · ${String(m.needs ?? 0)} necesidad(es)`,
  },
  cognitive_strategy: {
    title: "Eligió cómo consultar",
    body: (m) => `${String(m.primary ?? "—")} · ${String(m.representations ?? 0)} representación(es)`,
  },
  cognitive_entities: {
    title: "Identificó entidades",
    body: (m) => `${String(m.mentions ?? 0)} mención(es) · resueltas: ${m.resolved ? "sí" : "no"}`,
  },
  cognitive_runner: {
    title: "Consultó una representación",
    body: (m) => `${String(m.representation ?? "—")} · ${String(m.count ?? 0)} resultado(s) · ${String(m.latency_ms ?? 0)} ms`,
  },
  cognitive_evidence: {
    title: "Ensambló la evidencia",
    body: (m) => `${String(m.count ?? 0)} evidencia(s) · ${String(m.conflicts ?? 0)} conflicto(s) · descartadas: ${String(m.dropped ?? 0)}`,
  },
  cognitive_brief: {
    title: "Comprimió el conocimiento",
    body: (m) => `${String(m.chars ?? 0)} caracteres · ${String(m.sections ?? 0)} sección(es)`,
  },
  cognitive_verification: {
    title: "Verificó la respuesta",
    body: (m) => `${String(m.action ?? "—")} · sin respaldo: ${String(m.unsupported ?? 0)} · conflictos: ${String(m.conflicted ?? 0)}`,
  },
  cognitive_budget: {
    title: "Dentro del presupuesto",
    body: (m) => `${String(m.tokens ?? 0)}/${String(m.max_tokens ?? "—")} tokens · ${String(m.llm_calls ?? 0)} llamada(s)`,
  },
  cognitive_loop: {
    title: "Rondas de búsqueda",
    body: (m) => `${String(m.count ?? 0)} ronda(s)${m.extra_round ? " · ronda extra" : ""}${m.exhausted ? " · agotado" : ""}`,
  },
  cognitive_learning: {
    title: "Señales de aprendizaje",
    body: (m) => `${String(m.count ?? 0)} señal(es)`,
  },
  cognitive_deep_run: {
    title: "Investigación profunda",
    body: (m) => `${String(m.status ?? "—")}${m.failure_mode ? ` · ${String(m.failure_mode)}` : ""} · ${String(m.tokens ?? 0)} tokens`,
  },
};

function record(value: unknown): Record<string, unknown> {
  return typeof value === "object" && value !== null
    ? (value as Record<string, unknown>)
    : {};
}

export function parseCognitiveStory(value: unknown): CognitiveStory | null {
  const root = record(value);
  const normal = root.normal;
  if (!Array.isArray(normal)) return null;
  const steps: CognitiveStoryStep[] = [];
  for (const raw of normal) {
    const step = record(raw);
    if (typeof step.kind !== "string") return null;
    steps.push({
      kind: step.kind,
      phase: String(step.phase ?? ""),
      status: String(step.status ?? "ok"),
      metrics: record(step.metrics),
    });
  }
  return {
    schemaVersion: Number(root.schema_version ?? 1),
    normal: steps,
    expanded: record(root.expanded),
    raw: record(root.raw),
  };
}
