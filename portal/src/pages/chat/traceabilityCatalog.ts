// =============================================================================
// Catálogo central de traducción — Traceability Schema v2
// =============================================================================
// Única fuente de textos para métricas, glosario, estados de diagnóstico,
// controles y pasos del journey. Los componentes NO hardcodean explicaciones:
// consumen estas funciones con los params reales de la telemetría.
import {
  EFFECT_LABELS,
  JUDGMENT_VALUE_LABELS,
  QUESTION_LABELS,
} from "./executionStory";
import type { Tone } from "../../components/ui";

export { EFFECT_LABELS, JUDGMENT_VALUE_LABELS, QUESTION_LABELS };

type Params = Record<string, unknown>;

function n(params: Params, key: string): number | null {
  const value = params[key];
  if (typeof value === "number" && Number.isFinite(value)) return value;
  if (typeof value === "string" && value.trim() !== "") {
    const parsed = Number(value);
    return Number.isFinite(parsed) ? parsed : null;
  }
  return null;
}

function pct(value: number | null): string {
  if (value === null) return "—";
  const percent = value * 100;
  return `${percent >= 10 ? Math.round(percent) : percent.toFixed(1)}%`;
}

/* --- Severidad y dimensiones --------------------------------------------- */

export type Severity = "INFO" | "NOTICE" | "WARNING" | "ERROR" | "CRITICAL";

export const SEVERITY_META: Record<Severity, { label: string; tone: Tone; order: number }> = {
  INFO: { label: "Informativo", tone: "neutral", order: 0 },
  NOTICE: { label: "Aviso", tone: "info", order: 1 },
  WARNING: { label: "Advertencia", tone: "warn", order: 2 },
  ERROR: { label: "Error", tone: "danger", order: 3 },
  CRITICAL: { label: "Crítico", tone: "danger", order: 4 },
};

export type DimensionStatus = "ok" | "notice" | "warning" | "error" | "unknown";

export const DIMENSION_STATUS_META: Record<
  DimensionStatus,
  { label: string; tone: Tone; symbol: string }
> = {
  ok: { label: "Correcto", tone: "ok", symbol: "🟢" },
  notice: { label: "Con avisos", tone: "info", symbol: "🟡" },
  warning: { label: "Revisar", tone: "warn", symbol: "🟠" },
  error: { label: "Con problemas", tone: "danger", symbol: "🔴" },
  unknown: { label: "Sin datos", tone: "neutral", symbol: "⚪" },
};

export const DIMENSION_LABELS: Record<string, string> = {
  execution: "Estado general",
  evidence: "Evidencia",
  jev: "JEV",
  generation: "Generación",
  verification: "Verificación",
  memory: "Memoria",
  timing: "Tiempos",
  cost: "Costo",
  metadata: "Metadatos",
  consistency: "Consistencia",
  fallbacks: "Fallbacks y recuperación",
  presentation: "Presentación",
};

export const CONSISTENCY_META: Record<string, { label: string; tone: Tone }> = {
  consistent: { label: "Consistente", tone: "ok" },
  consistent_with_notes: { label: "Consistente con avisos", tone: "info" },
  partial: { label: "Parcialmente consistente", tone: "warn" },
  inconsistent: { label: "Inconsistente", tone: "danger" },
};

/* --- Titulares ------------------------------------------------------------ */

export const HEADLINE_META: Record<
  string,
  { title: string; tone: Tone; detail: string }
> = {
  RESPONSE_SUPPORTED: {
    title: "Respuesta respaldada",
    tone: "ok",
    detail: "Las afirmaciones principales quedaron respaldadas por las fuentes.",
  },
  RESPONSE_VERIFIED: {
    title: "Respuesta verificada",
    tone: "ok",
    detail: "La decisión determinista y su explicación quedaron verificadas.",
  },
  RESPONSE_DECISION_VERIFIED_NARRATIVE_PARTIAL: {
    title: "Decisión verificada · explicación parcialmente verificada",
    tone: "info",
    detail:
      "El resultado lo decidió código con respaldo; la explicación generada quedó parcial (por ejemplo, por un límite de generación o citas incompletas).",
  },
  RESPONSE_DECISION_VERIFIED_NARRATIVE_UNVERIFIED: {
    title: "Decisión verificada · explicación sin verificar",
    tone: "info",
    detail:
      "El resultado determinista está verificado; la explicación generada no pudo verificarse, sin afectar la decisión.",
  },
  RESPONSE_DECISION_NOT_VERIFIED: {
    title: "Decisión no verificada",
    tone: "danger",
    detail:
      "Una premisa o el respaldo de la decisión entró en conflicto; no se publica como verificada.",
  },
  RESPONSE_PARTIALLY_SUPPORTED: {
    title: "Respuesta con verificación parcial",
    tone: "warn",
    detail: "El respaldo documental se confirmó, pero parte de las comprobaciones no se observó.",
  },
  RESPONSE_INSUFFICIENT_EVIDENCE: {
    title: "Evidencia insuficiente",
    tone: "warn",
    detail: "La ejecución retuvo o limitó la respuesta por falta de evidencia.",
  },
  RESPONSE_CONFLICTING_EVIDENCE: {
    title: "Evidencia en conflicto",
    tone: "warn",
    detail: "Se detectaron fragmentos que se contradicen entre sí.",
  },
  RESPONSE_UNVERIFIED: {
    title: "Sin respaldo confirmado",
    tone: "danger",
    detail: "No se pudo confirmar el respaldo documental de la respuesta.",
  },
  RESPONSE_ABSTAINED: {
    title: "Zent retuvo la respuesta",
    tone: "warn",
    detail: "La evidencia no alcanzaba para responder con seguridad.",
  },
  RESPONSE_BLOCKED: {
    title: "Ejecución bloqueada",
    tone: "danger",
    detail: "La ejecución se detuvo antes de entregar una respuesta.",
  },
  RESPONSE_FAILED: {
    title: "La ejecución falló",
    tone: "danger",
    detail: "Ocurrió un error que impidió completar la respuesta.",
  },
};

/* --- Journey (§20) -------------------------------------------------------- */

export const JOURNEY_META: Record<
  string,
  { title: string; body: (params: Params) => string }
> = {
  QUERY_UNDERSTOOD: {
    title: "Entendió la consulta",
    body: () => "Interpretó qué se estaba preguntando antes de buscar.",
  },
  KNOWLEDGE_SEARCHED: {
    title: "Buscó conocimiento",
    body: (p) => {
      const retrieved = n(p, "retrieved");
      const deduplicated = n(p, "deduplicated");
      const unique = n(p, "unique");
      if (retrieved === null) return "Buscó en las fuentes disponibles.";
      const parts = [`Encontró ${retrieved} ${retrieved === 1 ? "fragmento" : "fragmentos"}.`];
      if (deduplicated !== null && deduplicated > 0) {
        parts.push(
          `${deduplicated} ${deduplicated === 1 ? "era duplicado o se solapaba" : "eran duplicados o se solapaban"}.`,
        );
      }
      if (unique !== null) {
        parts.push(
          `Quedaron ${unique} ${unique === 1 ? "evidencia útil" : "evidencias útiles"}.`,
        );
      }
      return parts.join(" ");
    },
  },
  EVIDENCE_ASSESSED: {
    title: "Evaluó la información",
    body: (p) => {
      const documents = n(p, "documents");
      const unique = n(p, "unique");
      const chunks = [
        documents !== null ? `${documents} ${documents === 1 ? "documento" : "documentos"}` : null,
        unique !== null ? `${unique} ${unique === 1 ? "evidencia" : "evidencias"}` : null,
      ].filter((chunk): chunk is string => Boolean(chunk));
      return chunks.length
        ? `Trabajó con ${chunks.join(" · ")}.`
        : "Revisó si la información alcanzaba.";
    },
  },
  EVIDENCE_INCOMPLETE: {
    title: "Evidencia incompleta",
    body: () => "Quedaron requisitos documentables sin cubrir; la respuesta lo declara.",
  },
  JEV_CHECKED: {
    title: "JEV revisó el camino",
    body: (p) => {
      const checks = n(p, "checks");
      const changed = p.changed_route === true;
      const requested = p.requested_more_evidence === true;
      const suffix = checks !== null ? `Realizó ${checks} ${checks === 1 ? "comprobación" : "comprobaciones"}.` : "";
      if (changed) {
        return `${suffix} Modificó la estrategia de la ejecución.`.trim();
      }
      if (requested) {
        return `${suffix} No cambió el camino, pero pidió más evidencia.`.trim();
      }
      return `${suffix} No fue necesario modificar la estrategia.`.trim();
    },
  },
  RETRIEVAL_RETRIED: {
    title: "Amplió la búsqueda",
    body: () => "JEV pidió otra ronda de evidencia antes de responder.",
  },
  PREMISES_CLOSED: {
    title: "Cerró premisas faltantes",
    body: (p) => {
      const rules = n(p, "rules_added");
      const evidence = n(p, "evidence_added");
      const termination = String(p.termination ?? "");
      if (termination === "SATISFIED") {
        return "Premise Closure recuperó las premisas que faltaban y quedaron satisfechas.";
      }
      const parts = [
        rules ? `${rules} ${rules === 1 ? "regla" : "reglas"} nueva${rules === 1 ? "" : "s"}` : null,
        evidence ? `${evidence} ${evidence === 1 ? "evidencia" : "evidencias"}` : null,
      ].filter((part): part is string => Boolean(part));
      return parts.length
        ? `Premise Closure sumó ${parts.join(" y ")}.`
        : "Premise Closure buscó las premisas que faltaban.";
    },
  },
  RULE_COMPILED: {
    title: "Ensambló la regla",
    body: (p) => {
      const rules = n(p, "rules");
      return rules !== null && rules > 0
        ? `El Rule Compiler produjo ${rules} ${rules === 1 ? "regla soportada" : "reglas soportadas"}.`
        : "El Rule Compiler ensambló una regla soportada con la evidencia disponible.";
    },
  },
  DETERMINISTIC_AUTHORITY: {
    title: "Decisión determinista",
    body: (p) => {
      const operation = String(p.operation ?? "");
      const result = String(p.result ?? "");
      return `La evaluación determinista produjo ${result || "un resultado"}${operation ? ` con ${operation}` : ""} y quedó bloqueada como autoritativa.`;
    },
  },
  REASONING_PREPARED: {
    title: "Preparó el razonamiento",
    body: (p) => {
      const calls = n(p, "calls");
      return calls !== null && calls > 1
        ? `Preparó el análisis en ${calls} llamadas al modelo.`
        : "Preparó el análisis antes de redactar.";
    },
  },
  RECOVERY_APPLIED: {
    title: "Aplicó una recuperación",
    body: (p) => `Se activó un control interno (${String(p.control_code ?? "recuperación")}).`,
  },
  ANSWER_GENERATED: {
    title: "Generó la respuesta",
    body: () => "Redactó la respuesta con la evidencia evaluada.",
  },
  ANSWER_VERIFIED: {
    title: "Verificó el respaldo",
    body: (p) => {
      const status = String(p.status ?? "");
      if (status === "VERIFIED") return "Las afirmaciones principales quedaron respaldadas por las fuentes.";
      if (status === "PARTIALLY_VERIFIED") return "El respaldo se confirmó, pero parte de las comprobaciones no se observó.";
      if (status === "CONFLICTING_EVIDENCE") return "Se detectaron fragmentos en conflicto.";
      if (status === "INSUFFICIENT_EVIDENCE") return "La evidencia no alcanzó para respaldar la respuesta.";
      return "No se pudo confirmar el respaldo documental.";
    },
  },
  ANSWER_DELIVERED: {
    title: "Entregó la respuesta",
    body: () => "La respuesta quedó disponible para el usuario.",
  },
};

/* --- Explicaciones contextuales (§22) ------------------------------------ */

export const EXPLANATION_META: Record<
  string,
  { question: string; answer: (params: Params) => string }
> = {
  MODEL_CALLS_PURPOSES: {
    question: "¿Por qué hubo varias llamadas al modelo?",
    answer: (p) => {
      const calls = n(p, "calls");
      const reasoning = n(p, "reasoning_calls");
      const answers = n(p, "answer_calls");
      const revisions = n(p, "revision_calls");
      const parts = [
        reasoning ? `${reasoning} ${reasoning === 1 ? "se usó" : "se usaron"} para razonamiento interno` : null,
        answers ? `${answers} para generar la respuesta final` : null,
        revisions ? `${revisions} para revisar la respuesta` : null,
      ].filter((part): part is string => Boolean(part));
      return calls !== null && parts.length
        ? `Hubo ${calls} llamadas: ${parts.join(" y ")}.`
        : "Cada llamada cumplió un propósito distinto dentro de la ejecución.";
    },
  },
  PARALLEL_TIME: {
    question: "¿Por qué las tareas suman más tiempo que la ejecución completa?",
    answer: (p) => {
      const wall = n(p, "wall_clock_ms");
      const accumulated = n(p, "accumulated_ms");
      if (wall === null || accumulated === null) {
        return "Algunas operaciones se ejecutaron en paralelo.";
      }
      return `Algunas operaciones se ejecutaron en paralelo: la espera real fue ${(wall / 1000).toFixed(1)} s y el trabajo medido suma ${(accumulated / 1000).toFixed(1)} s.`;
    },
  },
  USED_NOT_CITED: {
    question: "¿Por qué se utilizaron más evidencias de las que se citaron?",
    answer: (p) => {
      const difference = n(p, "difference") ?? 0;
      return `${difference} ${difference === 1 ? "evidencia ayudó" : "evidencias ayudaron"} a construir la respuesta sin quedar asociada a una afirmación final. No es un error: la cita marca respaldo explícito, no uso.`;
    },
  },
  DEDUPLICATION_SUMMARY: {
    question: "¿Por qué hay menos evidencias que fragmentos encontrados?",
    answer: (p) => {
      const retrieved = n(p, "retrieved");
      const deduplicated = n(p, "deduplicated");
      const unique = n(p, "unique");
      if (retrieved === null || unique === null) {
        return "Los fragmentos repetidos o solapados se agruparon en una sola evidencia.";
      }
      return `De ${retrieved} fragmentos, ${deduplicated ?? 0} eran duplicados o se solapaban; quedaron ${unique} evidencias únicas. La deduplicación evita contar dos veces el mismo contenido.`;
    },
  },
  JEV_CONFIRMED_NO_CHANGE: {
    question: "¿Por qué JEV aparece si no cambió nada?",
    answer: (p) => {
      const checks = n(p, "checks");
      return `JEV evaluó decisiones previas${checks !== null ? ` (${checks} ${checks === 1 ? "comprobación" : "comprobaciones"})` : ""} y confirmó que el camino seleccionado era adecuado. Que no cambie nada es un resultado, no una ausencia.`;
    },
  },
  JEV_CHANGED_PATH: {
    question: "¿Qué cambió JEV?",
    answer: (p) => {
      const decisions = Array.isArray(p.decisions) ? p.decisions : [];
      const actions = decisions
        .map((decision) =>
          typeof decision === "object" && decision !== null
            ? String((decision as Record<string, unknown>).action ?? "")
            : "",
        )
        .filter(Boolean)
        .map((action) => EFFECT_LABELS[action] ?? action);
      return actions.length
        ? `JEV cambió la estrategia: ${actions.join(", ")}.`
        : "JEV modificó una decisión de la ejecución.";
    },
  },
  MAX_TOKENS_RECOVERY: {
    question: "¿Qué pasó con el límite de generación?",
    answer: (p) => {
      const impact = String(p.impact ?? "");
      if (impact === "RECOVERED_NO_IMPACT") {
        return "Se alcanzó un límite interno durante la generación, pero Zent lo resolvió automáticamente y la respuesta quedó íntegra.";
      }
      if (impact === "MINOR_DEGRADATION") {
        return "Se alcanzó un límite interno; la respuesta se completó con una degradación menor registrada.";
      }
      if (impact === "POSSIBLY_INCOMPLETE") {
        return "Se alcanzó un límite interno y la respuesta pudo quedar incompleta; la verificación lo refleja.";
      }
      return "El límite interno afectó materialmente la respuesta.";
    },
  },
  DECISION_VERIFIED: {
    question: "¿Cómo se verificó la decisión?",
    answer: (p) => {
      const result = String(p.result ?? "");
      const operation = String(p.operation ?? "determinista");
      const premises = String(p.premise_status ?? "");
      return `El resultado ${result || "de la decisión"} se obtuvo por código con la operación ${operation}${premises ? ` y premisas ${premises}` : ""}; no depende del texto generado.`;
    },
  },
  DECISION_NOT_VERIFIED: {
    question: "¿Por qué la decisión no está verificada?",
    answer: () =>
      "Una premisa o el respaldo de la decisión entró en conflicto. Por seguridad no se publica como verificada hasta resolver el conflicto.",
  },
  DECISION_UNDETERMINED: {
    question: "¿Por qué no hay decisión verificada?",
    answer: () =>
      "No se produjo una decisión determinista autoritativa para esta pregunta; el estado global se evalúa por la vía documental.",
  },
  NARRATIVE_PARTIAL: {
    question: "¿Por qué la explicación quedó parcial?",
    answer: () =>
      "Parte de la explicación generada no pudo verificarse por completo (citación o respaldo documental del texto). La decisión determinista, si existe, no cambia.",
  },
  NARRATIVE_TRUNCATED: {
    question: "¿La explicación quedó incompleta?",
    answer: (p) =>
      String(p.warning ?? "") ||
      "La explicación pudo quedar incompleta; el resultado determinista no fue afectado.",
  },
  NARRATIVE_UNVERIFIED: {
    question: "¿Por qué la explicación no se verificó?",
    answer: () =>
      "No se pudo confirmar el respaldo documental de la explicación generada. La decisión determinista, si existe, se verifica por separado.",
  },
  FALLBACK_TAXONOMY: {
    question: "¿Ocurrió algún fallback?",
    answer: (p) => {
      const classes = (p.classes ?? {}) as Record<string, number>;
      const names = Object.entries(classes)
        .filter(([, count]) => Number(count) > 0)
        .map(([kind, count]) => `${FALLBACK_CLASS_LABELS[kind] ?? kind} (${count})`);
      return names.length
        ? `Se registraron eventos de recuperación: ${names.join(", ")}.`
        : "No se registraron fallbacks.";
    },
  },
  PARTIAL_EVIDENCE_DETAIL: {
    question: "¿Por qué algunos fragmentos no aparecen en el detalle?",
    answer: (p) => {
      const collected = n(p, "collected");
      const retrieved = n(p, "retrieved");
      return retrieved !== null && collected !== null
        ? `Se recuperaron ${retrieved} fragmentos, pero el detalle disponible sólo incluye ${collected}. Los conteos no se ajustan artificialmente.`
        : "El detalle de evidencia disponible está truncado; no se inventan fragmentos.";
    },
  },
  HISTORICAL_TRACE: {
    question: "¿Por qué esta ejecución muestra menos detalle?",
    answer: () =>
      "La ejecución es anterior al esquema v2 y se adaptó con fidelidad parcial: sólo se muestra lo que la telemetría original guardó.",
  },
};

export const FALLBACK_CLASS_LABELS: Record<string, string> = {
  warning: "Aviso sin impacto",
  recoverable_event: "Evento recuperado",
  retry: "Reintento",
  continuation: "Continuación",
  provider_fallback: "Proveedor alternativo",
  model_fallback: "Modelo alternativo",
  retrieval_fallback: "Búsqueda alternativa",
  material_fallback: "Fallback con impacto",
  fatal_error: "Error fatal",
};

/* --- Métricas (§11, §26) -------------------------------------------------- */

export const METRIC_HELP: Record<
  string,
  { label: string; scale: string; description: string }
> = {
  selected_probability: {
    label: "Probabilidad de la opción elegida",
    scale: "0% – 100%",
    description:
      "Peso que la propia distribución de JEV asignó a la opción seleccionada. Es una probabilidad medida, no una confianza derivada.",
  },
  confidence: {
    label: "Confianza derivada",
    scale: "0% – 100%",
    description:
      "Indicador derivado de qué tan sólida fue la decisión según JEV. Puede diferir de la probabilidad de la opción: por eso se muestran por separado.",
  },
  certainty: {
    label: "Certeza",
    scale: "0% – 100%",
    description: "Certeza declarada para juicios de tipo noul (sí/no).",
  },
  margin: {
    label: "Margen",
    scale: "0% – 100%",
    description: "Diferencia entre la opción elegida y la segunda alternativa.",
  },
  entropy: {
    label: "Entropía",
    scale: "0 – 1",
    description:
      "Mide qué tan repartida estaba la decisión entre las alternativas. Cuanto mayor sea, menos clara era la elección.",
  },
  coverage_ratio: {
    label: "Cobertura de requisitos",
    scale: "0% – 100%",
    description: "Proporción de requisitos documentables cubiertos por evidencia.",
  },
  score: {
    label: "Score de recuperación",
    scale: "0 – 1",
    description: "Puntaje del retrieval para este fragmento. Comparable sólo dentro de la misma configuración de búsqueda.",
  },
  rerank_score: {
    label: "Score de reranking",
    scale: "Interno",
    description: "Puntaje del reranker. Es una métrica interna: no comparable entre ejecuciones ni proveedores.",
  },
  quality: {
    label: "Calidad del answer gate",
    scale: "0 – 3",
    description:
      "Métrica interna del gate de respuesta (escala 0–3). Es experimental: no comparable entre versiones del gate.",
  },
  wall_clock_ms: {
    label: "Tiempo real percibido",
    scale: "Milisegundos",
    description: "Tiempo total que esperó el usuario, contado de inicio a fin.",
  },
  accumulated_ms: {
    label: "Trabajo interno acumulado",
    scale: "Milisegundos",
    description:
      "Suma de las duraciones medidas. Puede superar el tiempo real porque algunas tareas se ejecutan en paralelo.",
  },
  cost_usd: {
    label: "Costo",
    scale: "USD",
    description: "Costo medido de la ejecución con los precios configurados del proveedor.",
  },
};

/* --- Glosario (§23) ------------------------------------------------------- */

export const GLOSSARY: Record<string, { term: string; short: string; more: string }> = {
  jev: {
    term: "JEV",
    short: "Capa de juicios que evalúa decisiones antes y después de generar.",
    more: "JEV observa el estado de la ejecución y responde preguntas (sí/no, opciones, scores). Sus respuestas pueden confirmar el camino o cambiarlo. Ejecutar JEV no equivale a intervenir: la intervención es material sólo cuando una decisión aplicada cambia o bloquea el resultado.",
  },
  gate: {
    term: "Gate",
    short: "Comprobación que habilita o bloquea un paso.",
    more: "Un gate evalúa una condición (evidencia suficiente, respuesta respaldada, formato correcto) y decide si la ejecución puede avanzar tal cual.",
  },
  retrieval: {
    term: "Retrieval",
    short: "Búsqueda de fragmentos relevantes en las fuentes.",
    more: "Recupera candidatos desde el índice. Lo recuperado todavía no es evidencia: pasa por deduplicación, selección y evaluación antes de usarse.",
  },
  reranking: {
    term: "Reranking",
    short: "Reordenamiento de los fragmentos recuperados por relevancia.",
    more: "El reranker vuelve a puntuar los candidatos para elegir cuáles entran al contexto final.",
  },
  evidence: {
    term: "Evidencia",
    short: "Fragmento canónico de una fuente, con identidad y ubicación.",
    more: "Una evidencia es una unidad lógica: mismo documento, misma ubicación y mismo texto se cuentan una sola vez, aunque el retrieval los haya encontrado varias veces.",
  },
  semantic_unit: {
    term: "Unidad semántica",
    short: "Bloque de contenido derivado durante la ingesta.",
    more: "Puede haber varias unidades del mismo documento físico. La identidad canónica evita contarlas como documentos distintos.",
  },
  fallback: {
    term: "Fallback",
    short: "Mecanismo alternativo ante un problema.",
    more: "No todo fallback es un error: un reintento, un proveedor alternativo o continuar tras un límite son eventos distintos. La trazabilidad clasifica cada uno y declara si tuvo efecto material.",
  },
  grounding: {
    term: "Grounding",
    short: "Grado en que la respuesta se apoya en las fuentes.",
    more: "El grounding compara la respuesta con la evidencia disponible para detectar afirmaciones sin respaldo.",
  },
  verified: {
    term: "Verificado",
    short: "El respaldo documental fue confirmado.",
    more: "Verificado exige que las comprobaciones principales hayan corrido y hayan confirmado el respaldo. Una comprobación no observada deja la verificación en parcial.",
  },
  entropy: {
    term: "Entropía",
    short: "Qué tan repartida estaba una decisión entre alternativas.",
    more: "Entropía alta significa que varias opciones tenían peso similar: la decisión era poco clara aunque una haya ganado.",
  },
  margin: {
    term: "Margen",
    short: "Distancia entre la opción elegida y la segunda.",
    more: "Un margen pequeño indica una decisión reñida; la UI puede marcarla como incierta sin convertirla en error.",
  },
  span: {
    term: "Span",
    short: "Operación medida con inicio y duración.",
    more: "Los spans pueden contener otros spans y ejecutarse en paralelo; por eso su suma puede superar el tiempo real percibido.",
  },
  wall_clock: {
    term: "Wall clock",
    short: "Tiempo real de pared: lo que esperó el usuario.",
    more: "Es la única cifra que representa la espera del usuario. El trabajo interno acumulado se informa aparte.",
  },
  canonical_event: {
    term: "Evento canónico",
    short: "Paso del pipeline con fase, estado y métricas.",
    more: "Los eventos son la base de la timeline y de la historia. Un step del runtime sin mapeo no se descarta: se conserva con su tipo original.",
  },
  deduplication: {
    term: "Deduplicación",
    short: "Fusión de fragmentos que representan la misma evidencia.",
    more: "Tres capas: duplicado exacto, solapamiento de chunking y similitud semántica fuerte. Nunca fusiona documentos distintos ni evidencia complementaria.",
  },
  canonical_source: {
    term: "Fuente canónica",
    short: "Identidad estable del documento físico.",
    more: "Se deriva del archivo original (tenant, base de conocimiento, file id, URI, nombre o hash), no del id generado durante el procesamiento.",
  },
  evidence_id: {
    term: "Evidence ID",
    short: "Identificador de una evidencia lógica.",
    more: "Si el runtime no lo proveyó, se deriva de forma determinística desde fuente, ubicación y hash del texto.",
  },
  intervention: {
    term: "Intervención",
    short: "Decisión de JEV que cambió o bloqueó la ejecución.",
    more: "Una confirmación (por ejemplo, generar) no es intervención material, aunque quede registrada como decisión aplicada.",
  },
  warning: {
    term: "Advertencia",
    short: "Anomalía registrada que puede no afectar la respuesta.",
    more: "Severidad y efecto material son ejes distintos: un warning técnico puede tener material_effect=false.",
  },
  material_effect: {
    term: "Efecto material",
    short: "El evento cambió el resultado de la ejecución.",
    more: "Un límite recuperado sin impacto no es material; un truncamiento que degrada la respuesta sí.",
  },
};

/* --- Controles (§15) ------------------------------------------------------ */

export const CONTROL_META: Record<
  string,
  {
    title: string;
    happened: string;
    action: string;
    state: (params: Params, recovered: boolean) => string;
  }
> = {
  MAX_TOKENS_REACHED: {
    title: "Límite de generación alcanzado",
    happened: "El modelo llegó al límite configurado de salida.",
    action: "Zent continuó la ejecución y completó la respuesta.",
    state: (params, recovered) => {
      const impact = String(params.impact ?? "");
      if (impact === "POSSIBLY_INCOMPLETE") return "Respuesta posiblemente incompleta";
      if (impact === "MATERIAL_ERROR") return "Error material";
      if (impact === "MINOR_DEGRADATION") return "Degradación menor";
      return recovered ? "Resuelto automáticamente" : "Requiere revisión";
    },
  },
  COST_LIMIT_REACHED: {
    title: "Límite de costo alcanzado",
    happened: "La ejecución alcanzó el costo máximo configurado.",
    action: "Zent cerró la generación con lo producido.",
    state: (_params, recovered) => (recovered ? "Resuelto automáticamente" : "Requiere revisión"),
  },
  TOOL_CALL_LIMIT_REACHED: {
    title: "Límite de herramientas alcanzado",
    happened: "Se alcanzó el número máximo de llamadas a herramientas.",
    action: "Zent detuvo las herramientas y continuó.",
    state: (_params, recovered) => (recovered ? "Resuelto automáticamente" : "Requiere revisión"),
  },
  EXECUTION_TIME_LIMIT_REACHED: {
    title: "Límite de tiempo alcanzado",
    happened: "La ejecución alcanzó el tiempo máximo configurado.",
    action: "Zent cerró el run y entregó lo disponible.",
    state: (_params, recovered) => (recovered ? "Resuelto automáticamente" : "Requiere revisión"),
  },
  STEP_LIMIT_REACHED: {
    title: "Límite de pasos alcanzado",
    happened: "Se alcanzó el número máximo de pasos.",
    action: "Zent finalizó la ejecución.",
    state: (_params, recovered) => (recovered ? "Resuelto automáticamente" : "Requiere revisión"),
  },
  MODEL_PROTECTION_TRIGGERED: {
    title: "Protección de modelo activada",
    happened: "El presupuesto del modelo se agotó.",
    action: "Zent degradó el modelo de forma controlada.",
    state: (_params, recovered) => (recovered ? "Resuelto automáticamente" : "Requiere revisión"),
  },
  MODEL_CIRCUIT_OPEN: {
    title: "Circuito del modelo abierto",
    happened: "El proveedor del modelo no estaba disponible.",
    action: "Zent intentó una alternativa.",
    state: (_params, recovered) => (recovered ? "Recuperado con alternativa" : "Requiere revisión"),
  },
  PROVIDER_RATE_LIMIT: {
    title: "Límite de tasa del proveedor",
    happened: "El proveedor rechazó temporalmente la petición.",
    action: "Zent reintentó o usó un respaldo.",
    state: (_params, recovered) => (recovered ? "Resuelto automáticamente" : "Requiere revisión"),
  },
  PROVIDER_QUOTA_EXCEEDED: {
    title: "Cuota del proveedor agotada",
    happened: "El proveedor agotó la cuota configurada.",
    action: "Zent usó un proveedor alternativo si estaba disponible.",
    state: (_params, recovered) => (recovered ? "Recuperado con alternativa" : "Requiere revisión"),
  },
  RETRIEVAL_BLOCKED: {
    title: "Búsqueda bloqueada",
    happened: "La búsqueda de evidencia se bloqueó por una protección.",
    action: "Zent continuó sin esa búsqueda.",
    state: (_params, recovered) => (recovered ? "Resuelto automáticamente" : "Requiere revisión"),
  },
  MALFORMED_MODEL_OUTPUT: {
    title: "Salida del modelo inválida",
    happened: "El modelo devolvió un formato que no se pudo interpretar.",
    action: "Zent reprocesó la salida.",
    state: (_params, recovered) => (recovered ? "Resuelto automáticamente" : "Requiere revisión"),
  },
  LOOP_PREVENTED: {
    title: "Bucle prevenido",
    happened: "Se detectó una repetición que no aportaba información.",
    action: "Zent cortó el bucle.",
    state: (_params, recovered) => (recovered ? "Resuelto automáticamente" : "Requiere revisión"),
  },
  EMBEDDING_FALLBACK: {
    title: "Embedding alternativo",
    happened: "El proveedor de embeddings principal no respondió.",
    action: "Zent usó el proveedor de respaldo.",
    state: () => "Resuelto automáticamente",
  },
  VERIFIER_FALLBACK: {
    title: "Verificador alternativo",
    happened: "El verificador principal no estaba disponible.",
    action: "Zent usó una validación alternativa.",
    state: () => "Resuelto automáticamente",
  },
  ANSWER_REVISED: {
    title: "Respuesta corregida",
    happened: "Una comprobación detectó algo que corregir en la respuesta.",
    action: "Zent reescribió la respuesta.",
    state: () => "Resuelto automáticamente",
  },
  PROVIDER_FALLBACK: {
    title: "Fallback de proveedor",
    happened: "El proveedor principal falló.",
    action: "Zent usó un proveedor alternativo.",
    state: () => "Resuelto automáticamente",
  },
  MODEL_FALLBACK: {
    title: "Fallback de modelo",
    happened: "El modelo principal no estaba disponible.",
    action: "Zent usó un modelo alternativo.",
    state: () => "Resuelto automáticamente",
  },
  RETRIEVAL_FALLBACK: {
    title: "Búsqueda alternativa",
    happened: "La búsqueda principal no estaba disponible.",
    action: "Zent usó una búsqueda alternativa.",
    state: () => "Resuelto automáticamente",
  },
  FATAL_ERROR: {
    title: "Error fatal",
    happened: "La ejecución no pudo continuar.",
    action: "Zent detuvo el run.",
    state: () => "No recuperado",
  },
};

/* --- Diagnóstico (§18) ---------------------------------------------------- */

export interface DiagnosticCopy {
  title: string;
  meaning: (params: Params) => string;
  impact: (params: Params) => string;
  fix: (params: Params) => string;
}

const UPSTREAM_IMPACT = "No se detectó impacto en el contenido de la respuesta.";

export const DIAGNOSTIC_COPY: Record<string, DiagnosticCopy> = {
  EVIDENCE_ID_MISSING: {
    title: "Identificador de evidencia ausente",
    meaning: () =>
      "Un fragmento recuperado no tiene todavía un identificador canónico.",
    impact: () => UPSTREAM_IMPACT,
    fix: () =>
      "Regenerar el evidence_id a partir de la fuente, ubicación y hash del fragmento.",
  },
  EVIDENCE_EXCERPT_MISSING: {
    title: "Fragmento sin texto visible",
    meaning: () => "Una evidencia utilizada no conserva su excerpt en la telemetría.",
    impact: () => UPSTREAM_IMPACT,
    fix: () => "Persistir el excerpt del fragmento en el registro de evidencia.",
  },
  SOURCE_NAME_MISSING: {
    title: "Fuente sin nombre normalizado",
    meaning: (p) =>
      `La fuente canónica ${String(p.canonical_source_id ?? "")} no tiene nombre legible: sólo se dispone de ids generados.`.trim(),
    impact: () => UPSTREAM_IMPACT,
    fix: () =>
      "Persistir el nombre original del archivo (o el título del perfil de fuente) durante la ingesta.",
  },
  CANONICAL_SOURCE_ID_MISSING: {
    title: "Fuente canónica sin identidad",
    meaning: () => "Una evidencia no pudo asociarse a ninguna fuente física identificable.",
    impact: () => UPSTREAM_IMPACT,
    fix: () => "Registrar file id, URI o nombre normalizado al ingerir el documento.",
  },
  CANONICAL_SOURCE_WEAK_IDENTITY: {
    title: "Identidad de fuente débil",
    meaning: (p) => {
      const count = n(p, "count");
      const basis = String(p.identity_basis ?? "un id generado");
      if (count !== null && count > 1) {
        return `${count} fuentes canónicas se derivaron de ${basis}, que puede no sobrevivir a una reingesta.`;
      }
      return `La identidad se derivó de ${basis}, que puede no sobrevivir a una reingesta.`;
    },
    impact: () => UPSTREAM_IMPACT,
    fix: () => "Persistir el archivo original (file id, URI o hash) como ancla de identidad.",
  },
  EVIDENCE_COLLECTION_PARTIAL: {
    title: "Detalle de evidencia parcial",
    meaning: (p) =>
      `Se declararon ${String(p.declared_retrieved ?? "varios")} fragmentos, pero la telemetría sólo entrega el detalle de ${String(p.collected ?? "algunos")}.`,
    impact: () => "Los conteos de evidencias únicas quedan sin confirmar; no se inventan.",
    fix: () => "Elevar el límite de detalle de evidencia persistido.",
  },
  EVIDENCE_COLLECTION_EXCEEDS_DECLARED: {
    title: "Detalle mayor que lo declarado",
    meaning: (p) =>
      `Se recolectaron ${String(p.collected ?? "")} fragmentos y el runtime declaró ${String(p.declared_retrieved ?? "")}.`,
    impact: () => UPSTREAM_IMPACT,
    fix: () => "Alinear el conteo declarado con la evidencia efectivamente expuesta.",
  },
  EVIDENCE_DETAIL_UNAVAILABLE: {
    title: "Detalle de evidencia no disponible",
    meaning: (p) =>
      `El runtime declaró ${String(p.declared_retrieved ?? "")} fragmentos pero no publicó su detalle.`,
    impact: () => "No se pudo verificar la deduplicación ni las citas contra el detalle.",
    fix: () => "Publicar items_detail en el bloque de evidencia.",
  },
  EVIDENCE_DEDUPLICATED: {
    title: "Evidencias duplicadas fusionadas",
    meaning: (p) =>
      `${String(p.deduplicated ?? "")} fragmentos se fusionaron por duplicado exacto, solapamiento o similitud.`,
    impact: () => "Ninguno: la deduplicación evita contar dos veces el mismo contenido.",
    fix: () => "No requiere corrección.",
  },
  CITATION_DANGLING: {
    title: "Cita sin evidencia canónica",
    meaning: (p) =>
      `Hay citas que apuntan a evidencias no presentes en la colección (${Array.isArray(p.evidence_ids) ? p.evidence_ids.join(", ") : ""}).`.trim(),
    impact: () => "Una cita podría no estar respaldada por el detalle recuperado.",
    fix: () => "Alinear los ids de cita con los del registro de evidencia.",
  },
  CITATION_EVIDENCE_REFERENTIAL_INTEGRITY: {
    title: "Cita con referencia inexistente",
    meaning: (p) => {
      const count = n(p, "count");
      const ids = Array.isArray(p.evidence_ids) ? p.evidence_ids.join(", ") : "";
      if (count !== null && count > 1) {
        return `${count} citas apuntan a evidence_ids que no existen en el registro canónico (${ids}). Esas citas no se publican.`;
      }
      return `Una cita apunta a un evidence_id que no existe en el registro canónico (${ids}). Esa cita no se publica.`;
    },
    impact: () => "La cita se descarta para no mostrar respaldo inexistente.",
    fix: () => "Alinear los ids de cita con los del registro de evidencia.",
  },
  CITATION_REFERENCES_COLLAPSED: {
    title: "Referencias de cita repetidas",
    meaning: (p) =>
      `${String(p.references ?? "")} referencias apuntan a ${String(p.unique ?? "")} evidencias únicas; ${String(p.collapsed ?? "")} se repitieron.`,
    impact: () => "Ninguno: el conteo de evidencias citadas usa ids únicos.",
    fix: () => "No requiere corrección.",
  },
  PROBABILITY_MISMATCH: {
    title: "Probabilidad y confianza no coinciden",
    meaning: (p) =>
      `La opción elegida (${String(p.outcome_key ?? "")}) tiene probabilidad ${pct(n(p, "selected_probability"))} en su distribución, mientras la confianza derivada reportada es ${pct(n(p, "confidence"))}.`,
    impact: () =>
      "No afecta la respuesta. La UI muestra ambas métricas etiquetadas para no confundirlas.",
    fix: () =>
      "Revisar al productor del juicio: la confianza derivada no debería presentarse como probabilidad de la opción.",
  },
  INVALID_PROBABILITY: {
    title: "Probabilidad fuera de rango",
    meaning: (p) => `Se recibió ${String(p.raw_value ?? "")} como probabilidad (rango válido 0–1).`,
    impact: () => "El valor se descartó en vez de mostrarse incorrectamente.",
    fix: () => "Corregir el productor del juicio para emitir valores en 0–1.",
  },
  ACTION_APPLIED_REQUIRED: {
    title: "Decisión accionable sin aplicar",
    meaning: (p) =>
      `La decisión ${String(p.decision_id ?? "")} está clasificada como ${String(p.classification ?? "")} pero no se aplicó.`,
    impact: () => UPSTREAM_IMPACT,
    fix: () => "Alinear la clasificación con el flag `applied`.",
  },
  INSUFFICIENT_THEN_GENERATED: {
    title: "Respuesta tras evidencia insuficiente",
    meaning: (p) =>
      `La primera ronda declaró evidencia insuficiente (${String(p.rounds ?? "")} rondas) y la respuesta se generó sin ampliación registrada.`,
    impact: () => "La respuesta podría no estar respaldada por completa.",
    fix: () => "Registrar la ampliación o el fallback que justificó continuar.",
  },
  EVIDENCE_USED_EXCEEDS_UNIQUE: {
    title: "Se usó más evidencia que la única",
    meaning: (p) =>
      `Se declararon ${String(p.used ?? "")} evidencias usadas y sólo ${String(p.unique ?? "")} únicas.`,
    impact: () => "Los conteos de evidencia son internamente inconsistentes.",
    fix: () => "Corregir el conteo de evidencia (probable doble conteo de chunks).",
  },
  EVIDENCE_CITED_EXCEEDS_USED: {
    title: "Se citó más de lo usado",
    meaning: (p) =>
      `Se declararon ${String(p.cited ?? "")} evidencias citadas y ${String(p.used ?? "")} usadas.`,
    impact: () => "Una cita podría apuntar a evidencia no utilizada.",
    fix: () => "Definir si una cita implica uso y alinear ambos conteos.",
  },
  EVIDENCE_SELECTED_EXCEEDS_UNIQUE: {
    title: "Selección mayor que la única",
    meaning: (p) =>
      `Se seleccionaron ${String(p.selected ?? "")} evidencias de ${String(p.unique ?? "")} únicas.`,
    impact: () => UPSTREAM_IMPACT,
    fix: () => "Revisar la selección: puede incluir ids duplicados.",
  },
  DOCUMENTS_USED_EXCEEDS_RETRIEVED: {
    title: "Documentos usados mayor que recuperados",
    meaning: (p) =>
      `Se usaron ${String(p.used ?? "")} documentos y sólo se recuperaron ${String(p.retrieved ?? "")}.`,
    impact: () => UPSTREAM_IMPACT,
    fix: () => "Alinear la identidad canónica de fuente entre recuperación y uso.",
  },
  EVIDENCE_DEDUP_ARITHMETIC: {
    title: "Conteo de deduplicación inconsistente",
    meaning: (p) =>
      `Recuperados (${String(p.retrieved ?? "")}) ≠ únicos (${String(p.unique ?? "")}) + duplicados (${String(p.deduplicated ?? "")}).`,
    impact: () => UPSTREAM_IMPACT,
    fix: () => "Corregir el conteo de deduplicación.",
  },
  ANSWER_CALLS_EXCEED_MODEL_CALLS: {
    title: "Respuestas mayor que llamadas al modelo",
    meaning: (p) =>
      `Se declararon ${String(p.answer_calls ?? "")} llamadas de respuesta y ${String(p.model_calls ?? "")} llamadas totales.`,
    impact: () => "La atribución de propósito del modelo es inconsistente.",
    fix: () => "Alinear los contadores de generación del runtime.",
  },
  MATERIAL_FALLBACK_WITHOUT_EVENT: {
    title: "Fallback material sin evento",
    meaning: () => "El trace declara fallback material pero no registra ningún evento de recuperación.",
    impact: () => "No se puede auditar qué cambió.",
    fix: () => "Registrar el evento material que acompañó al fallback.",
  },
  VERIFIED_WITH_MATERIAL_DEGRADATION: {
    title: "Verificado con degradación material",
    meaning: () => "La verificación figura como VERIFIED mientras existe una degradación material sin resolver.",
    impact: () => "La confianza mostrada no refleja el problema detectado.",
    fix: () => "Degradar la verificación a parcial o no verificada y explicar por qué.",
  },
  DECISION_VERIFICATION_CONSISTENCY: {
    title: "Decisión verificada marcada como no verificada",
    meaning: () =>
      "Con DecisionEnvelope autoritativo y un DerivedClaim determinista respaldado, la verificación de la decisión quedó en un estado distinto de VERIFIED.",
    impact: () => "La interfaz podría mostrar la decisión como no respaldada aunque la decidió código.",
    fix: () => "Separar la verificación de la narrativa: la decisión mantiene su estado VERIFIED.",
  },
  DECISION_NARRATIVE_SEPARATION: {
    title: "La narrativa degradó la decisión",
    meaning: () =>
      "Una decisión verificada convive con una verificación global no verificada: un problema de la explicación afectó el estado de la decisión.",
    impact: () => "El usuario podría creer que la decisión no está respaldada cuando sí lo está.",
    fix: () => "Recomponer el estado global desde la decisión verificada y la narrativa por separado.",
  },
  PARALLEL_SPANS: {
    title: "Trabajo interno en paralelo",
    meaning: (p) =>
      `El trabajo medido (${((n(p, "accumulated_ms") ?? 0) / 1000).toFixed(1)} s) supera la espera real (${((n(p, "wall_clock_ms") ?? 0) / 1000).toFixed(1)} s).`,
    impact: () => "Ninguno: es esperable cuando hay operaciones concurrentes.",
    fix: () => "No requiere corrección. Cada cifra describe algo distinto.",
  },
  MAX_TOKENS_RECOVERED: {
    title: "Límite de generación resuelto sin impacto",
    meaning: () => "Se alcanzó un límite interno durante la generación.",
    impact: () => "Ninguno detectado: la respuesta se completó y se mantuvo verificada.",
    fix: () => "No requiere corrección.",
  },
  MAX_TOKENS_MATERIAL_IMPACT: {
    title: "Límite de generación con impacto",
    meaning: (p) => {
      const impact = String(p.impact ?? "");
      if (impact === "POSSIBLY_INCOMPLETE") {
        return "La respuesta pudo quedar incompleta por el límite de generación.";
      }
      if (impact === "MATERIAL_ERROR") {
        return "El límite impidió completar la respuesta.";
      }
      return "El límite de generación dejó una degradación registrada.";
    },
    impact: () => "La verificación se degradó para reflejar el límite.",
    fix: () => "Revisar el truncamiento o elevar el presupuesto de tokens de salida.",
  },
  JOURNEY_DUPLICATE_PURPOSE: {
    title: "Paso duplicado en la historia",
    meaning: (p) =>
      `El propósito ${Array.isArray(p.purposes) ? p.purposes.join(", ") : ""} aparece más de una vez como generación visible.`,
    impact: () => "La historia podría sugerir que hubo dos respuestas.",
    fix: () => "Derivar los pasos visibles del propósito, no de cada model call.",
  },
  VERIFICATION_NOT_OBSERVED: {
    title: "Verificación no observada",
    meaning: () => "No se registró ninguna comprobación de verificación para esta ejecución.",
    impact: () => "No se puede confirmar el respaldo de la respuesta.",
    fix: () => "Emitir el bloque de verificación en el flow.",
  },
  HISTORICAL_TRACE_UPGRADED: {
    title: "Trazo histórico adaptado",
    meaning: (p) => `Esta ejecución usaba el esquema v${String(p.from_schema ?? 1)} y se adaptó al esquema v2.`,
    impact: () => "La fidelidad es parcial: sólo se muestra lo que la telemetría original guardó.",
    fix: () => "No requiere corrección; las ejecuciones nuevas emiten v2 completo.",
  },
  DUPLICATE_EVIDENCE_ID: {
    title: "Identificador de evidencia duplicado",
    meaning: () => "Dos evidencias distintas comparten el mismo evidence_id.",
    impact: () => UPSTREAM_IMPACT,
    fix: () => "Regenerar ids determinísticos por fuente, ubicación y hash.",
  },
  UNMAPPED_STEPS: {
    title: "Pasos sin mapeo canónico",
    meaning: (p) => `${String(p.count ?? "")} pasos del runtime no tienen traducción canónica.`,
    impact: () => UPSTREAM_IMPACT,
    fix: () => "Mapear el tipo de paso en `flow_story`.",
  },
};

export function diagnosticCopy(code: string): DiagnosticCopy {
  return (
    DIAGNOSTIC_COPY[code] ?? {
      title: code,
      meaning: () => "Hallazgo técnico sin explicación registrada.",
      impact: () => "Impacto no determinado.",
      fix: () => "Revisar la telemetría cruda de este hallazgo.",
    }
  );
}

export function severityMeta(severity: string) {
  return SEVERITY_META[severity as Severity] ?? SEVERITY_META.NOTICE;
}

export function dimensionStatusMeta(status: string) {
  return DIMENSION_STATUS_META[status as DimensionStatus] ?? DIMENSION_STATUS_META.unknown;
}

export function headlineMeta(code: string) {
  return (
    HEADLINE_META[code] ?? {
      title: "Ejecución sin estado canónico",
      tone: "neutral" as Tone,
      detail: "No se pudo interpretar el resultado de la ejecución.",
    }
  );
}
