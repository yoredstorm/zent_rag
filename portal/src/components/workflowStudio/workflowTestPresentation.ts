import { effectNodes, nodeMeta, type GraphIssue, type WorkflowGraph } from "../../lib/workflowGraph";
import type { RunDetail, RunStep } from "../WorkflowRunInspector";
import type { TestLevel, TestReportOut, TestRunKind } from "./workflowTestTypes";

export type TestTone = "neutral" | "info" | "ok" | "warn" | "danger";

export const LEVEL_LABEL: Record<TestLevel, string> = {
  preview: "Vista previa",
  simulation: "Simulación",
  sandbox: "Prueba sandbox",
  provider: "Proveedor",
};

export const LEVEL_DESCRIPTION: Record<TestLevel, string> = {
  preview: "No ejecuta nodos ni efectos. Sirve para revisar el recorrido previsto.",
  simulation:
    "Ejecuta el runner determinista. Puede hacer lecturas reales; las escrituras quedan limitadas o simuladas según el backend.",
  sandbox:
    "Solo si el backend tiene un sandbox conectado. Si no, el servidor degrada el nivel y lo informa.",
  provider:
    "Intenta verificación con proveedor real. Si no está conectado, el reporte queda UNVERIFIED. No publica el workflow.",
};

export const CAPPED_REASON_LABEL: Record<string, string> = {
  provider_adapter_unavailable: "Este entorno no permite certificar con proveedor real.",
  sandbox_adapter_unavailable: "Este entorno no tiene sandbox conectado.",
  no_external_capabilities: "El flujo no declara capacidades externas verificables.",
  credentials_not_configured: "Faltan credenciales de la integración.",
};

export const PREVIEW_LEVELS: TestLevel[] = ["preview", "simulation", "sandbox", "provider"];

export function normalizeLevel(value: string | null | undefined): TestLevel {
  return PREVIEW_LEVELS.includes(value as TestLevel) ? (value as TestLevel) : "simulation";
}

export function cappedReasonLabel(reason: string | null | undefined): string {
  const value = String(reason ?? "").trim();
  if (!value) return "";
  return CAPPED_REASON_LABEL[value] ?? value.replace(/[_-]+/g, " ");
}

export function requestedEffectiveSentence(report: TestReportOut): string {
  const requested = normalizeLevel(report.requested_level);
  const effective = normalizeLevel(report.effective_level);
  if (requested === effective) return `Nivel ejecutado: ${LEVEL_LABEL[effective]}.`;
  return `Solicitaste ${LEVEL_LABEL[requested]}. El servidor ejecutó ${LEVEL_LABEL[effective]}.`;
}

export function isJsonObject(value: string): boolean {
  const text = value.trim();
  if (!text.startsWith("{")) return false;
  try {
    const parsed = JSON.parse(text);
    return Boolean(parsed) && typeof parsed === "object" && !Array.isArray(parsed);
  } catch {
    return false;
  }
}

export function buildTestRun(report: TestReportOut): RunDetail {
  const steps: RunStep[] = (report.executed_nodes ?? []).map((raw, index) => {
    const item = (raw ?? {}) as Record<string, unknown>;
    return {
      step_index: index,
      step_type: String(item.type ?? item.node_type ?? "node"),
      node_id: item.node_id ? String(item.node_id) : null,
      node_type: item.node_type ? String(item.node_type) : null,
      status: String(item.status ?? "simulated"),
      output: (item.output as Record<string, unknown> | undefined) ?? {},
      error: item.error ? String(item.error) : null,
      duration_ms: item.duration_ms != null ? Number(item.duration_ms) : null,
    };
  });
  return {
    id: report.test_report_id ?? report.report_id ?? "test-report",
    status: String(report.result ?? "UNVERIFIED").toLowerCase(),
    steps,
    result: {},
  };
}

export type ResultHeadline = {
  tone: TestTone;
  label: string;
  detail: string;
};

export function resultHeadline(
  report: TestReportOut | null,
  run: RunDetail | null,
  runKind: TestRunKind | null,
): ResultHeadline {
  if (run && runKind === "execution_run") {
    const status = String(run.status ?? "").toLowerCase();
    if (status === "failed" || status === "denied") {
      return { tone: "danger", label: "La ejecución falló", detail: "Revisa el nodo marcado y el detalle técnico." };
    }
    if (status === "pending_approval") {
      return {
        tone: "warn",
        label: "Esperando aprobación",
        detail: "La ejecución no terminó. Hay una aprobación humana pendiente.",
      };
    }
    if (status === "waiting") {
      return {
        tone: "warn",
        label: "Esperando mensaje",
        detail: "El flujo quedó en espera. No hay respuesta final todavía.",
      };
    }
    if (status === "simulated") {
      return { tone: "info", label: "Ejecución simulada", detail: "No es una ejecución real." };
    }
    if (status === "succeeded") {
      return { tone: "ok", label: "Ejecución completada", detail: "Operación real finalizada." };
    }
    return { tone: "neutral", label: `Ejecución en estado ${status || "desconocido"}`, detail: "" };
  }

  if (!report) {
    return { tone: "neutral", label: "Sin resultado todavía", detail: "Prepara una prueba y ejecútala." };
  }

  const requested = normalizeLevel(report.requested_level);
  const effective = normalizeLevel(report.effective_level);
  const result = String(report.result ?? "").toUpperCase();

  if (result === "PREVIEW") {
    return {
      tone: "info",
      label: "Vista previa completada",
      detail: "No ejecutó nodos ni efectos. No es un pase.",
    };
  }
  if (result === "BLOCKED") {
    return {
      tone: "danger",
      label: "No se pudo probar",
      detail: report.why || "El servidor bloqueó la prueba.",
    };
  }
  if (result === "FAILED") {
    return {
      tone: "danger",
      label: "La prueba falló",
      detail: report.why || "Revisa el recorrido y el nodo marcado.",
    };
  }
  if (result === "UNVERIFIED") {
    return {
      tone: "warn",
      label: "Sin verificación de proveedor",
      detail:
        report.why ||
        cappedReasonLabel(report.capped_reason) ||
        "Falta un doble o una verificación real. No es PASSED.",
    };
  }
  if (result === "PASSED" && requested !== effective) {
    return {
      tone: "warn",
      label: "Nivel ajustado por el servidor",
      detail: `${requestedEffectiveSentence(report)} ${cappedReasonLabel(report.capped_reason)}`.trim(),
    };
  }
  if (result === "PASSED") {
    if (effective === "provider" && report.provider_verified) {
      return {
        tone: "ok",
        label: "Verificación con proveedor completada",
        detail: "El proveedor real fue usado. No publica el workflow.",
      };
    }
    if (effective === "sandbox") {
      return {
        tone: "ok",
        label: "Prueba sandbox completada",
        detail: "No certifica proveedor real ni publica el workflow.",
      };
    }
    return {
      tone: "ok",
      label: "Simulación completada",
      detail: "No certifica proveedor real ni publica el workflow.",
    };
  }
  if (result === "DECLARED") {
    return {
      tone: "warn",
      label: "Efectos declarados con datos de prueba",
      detail: "No es PASSED; falta sandbox o proveedor.",
    };
  }
  if (result === "SIMULATED") {
    return { tone: "info", label: "Efectos simulados", detail: "No es PASSED." };
  }
  if (result === "WAITING") {
    return { tone: "warn", label: "Esperando mensaje", detail: "El flujo no terminó." };
  }
  return {
    tone: "neutral",
    label: `Resultado ${result || "desconocido"}`,
    detail: report.why || "",
  };
}

export type ProviderSummary = {
  tone: TestTone;
  label: string;
  detail: string;
};

export function providerSummary(report: TestReportOut | null): ProviderSummary {
  if (!report) {
    return {
      tone: "neutral",
      label: "Disponibilidad no verificada",
      detail: "Se comprueba al ejecutar la prueba. No se deduce de etiquetas ni del entorno frontend.",
    };
  }
  if (report.provider_verified) {
    return {
      tone: "ok",
      label: "Verificado por proveedor",
      detail: "El backend emitió provider_verified=true. No implica publicación.",
    };
  }
  if (normalizeLevel(report.requested_level) === "provider") {
    return {
      tone: "warn",
      label: "Proveedor no conectado",
      detail: cappedReasonLabel(report.capped_reason) || "El servidor ejecutó un nivel inferior.",
    };
  }
  if (report.readiness?.provider_ready === false) {
    return {
      tone: "neutral",
      label: "Proveedor no disponible",
      detail: cappedReasonLabel(report.readiness?.reasons?.[0]) || "El reporte no acredita proveedor real.",
    };
  }
  return {
    tone: "neutral",
    label: "Proveedor no verificado",
    detail: "Este reporte no acredita una verificación con proveedor real.",
  };
}

export function effectBoundary(level: TestLevel): string {
  return LEVEL_DESCRIPTION[level];
}

/** Mensaje corto y honesto para el panel. Conserva códigos del backend. */
export function statusMessage(report: TestReportOut | null, runKind: TestRunKind | null): string {
  if (!report) return "";
  const requested = normalizeLevel(report.requested_level);
  const effective = normalizeLevel(report.effective_level);
  const result = String(report.result ?? "").toUpperCase();
  if (result === "PREVIEW") {
    return "Preview teórico. No ejecuta efectos y no es un pase.";
  }
  if (requested !== effective) {
    return `Nivel ${requested} no está conectado (${report.capped_reason ?? "sin adaptador"}). El servidor ejecutó ${effective}; no acredita proveedor real.`;
  }
  if (result === "UNVERIFIED") {
    return report.why || "UNVERIFIED: falta un doble o proveedor real. No es PASSED.";
  }
  if (result === "PASSED") {
    if (effective === "provider" && report.provider_verified) {
      return "Verificación con proveedor completada. No publica el workflow automáticamente.";
    }
    return `PASSED en ${effective} determinista. No certifica proveedor real ni publica solo.`;
  }
  if (result === "FAILED" || result === "BLOCKED") {
    return report.why || `El test terminó en ${result} en nivel ${effective}.`;
  }
  if (report.why) return report.why;
  return runKind === "execution_run"
    ? `La ejecución real terminó en ${String(report.result ?? "estado desconocido")}.`
    : `El test terminó en ${result || "estado desconocido"} en nivel ${effective}.`;
}

export function testRunSummary(report: TestReportOut): string {
  const count = report.executed_nodes?.length ?? 0;
  const requested = normalizeLevel(report.requested_level);
  const effective = normalizeLevel(report.effective_level);
  if (String(report.result).toUpperCase() === "PREVIEW") return `Vista previa · ${count} nodos previstos`;
  if (String(report.result).toUpperCase() === "FAILED") return `Prueba fallida · ${count} nodos ejecutados`;
  if (requested !== effective) return `Nivel ajustado a ${LEVEL_LABEL[effective]} · ${count} nodos`;
  return `${LEVEL_LABEL[effective]} terminada · ${count} nodos`;
}

export function flowPreview(graph: WorkflowGraph | null | undefined): string {
  if (!graph || graph.nodes.length === 0) return "Sin nodos en el grafo.";
  const labels = graph.nodes.slice(0, 7).map((node) => node.label || nodeMeta(node.type).label);
  const suffix = graph.nodes.length > 7 ? ` · +${graph.nodes.length - 7}` : "";
  return `${labels.join(" · ")}${suffix}`;
}

export function plannedEffectLabels(graph: WorkflowGraph | null | undefined): string[] {
  if (!graph) return [];
  return effectNodes(graph).map((node) => node.label || nodeMeta(node.type).label);
}

export function generateSampleForGraph(graph: WorkflowGraph | null | undefined): string {
  if (!graph || graph.nodes.length === 0) return "ejemplo";
  const types = new Set(graph.nodes.map((node) => node.type));
  if (types.has("query_business_data")) return "¿Cuál es el stock actual?";
  if (types.has("kb_query")) return "¿Qué dice la base de conocimiento sobre este caso?";
  if (types.has("llm")) return "Resume el último caso en una frase.";
  if (types.has("notify")) return "Avisar al equipo de prueba.";
  return "ejemplo";
}

export function shortHash(value: string | null | undefined): string {
  const text = String(value ?? "");
  return text.length > 12 ? `${text.slice(0, 12)}…` : text;
}

export function formatElapsed(ms: number): string {
  const total = Math.max(0, Math.floor(ms / 1000));
  if (total < 60) return `${total}s`;
  const minutes = Math.floor(total / 60);
  const seconds = total % 60;
  return `${minutes}m ${String(seconds).padStart(2, "0")}s`;
}

export function graphIssueSummary(issues: GraphIssue[]): string {
  if (issues.length === 0) return "Sin avisos del grafo.";
  if (issues.length === 1) return `${issues[0].label}: ${issues[0].message}`;
  return `${issues[0].label}: ${issues[0].message} · +${issues.length - 1} más`;
}

export function resultPaneLabel(pane: "answer" | "path" | "verification"): string {
  if (pane === "path") return "Recorrido";
  if (pane === "verification") return "Verificación";
  return "Respuesta";
}
