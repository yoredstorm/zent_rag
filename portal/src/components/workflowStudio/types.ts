import type { WorkflowGraph } from "../../lib/workflowGraph";

/** Paso del motor legacy `steps[]` (workflows creados antes del canvas v2). */
export type WorkflowStep = {
  type: string;
  config: Record<string, unknown>;
  then?: WorkflowStep[];
  else?: WorkflowStep[];
};

export type WorkflowSummary = {
  id: string;
  name: string;
  description: string | null;
  trigger_type: string;
  status: string;
  runs: number;
  ok_runs: number;
  created_at?: string;
  updated_at?: string;
};

export type WorkflowTemplate = {
  slug: string;
  name: string;
  description: string;
  category: string;
  trigger_type: string;
  steps: { type: string }[];
};

export type WorkflowDetail = {
  id: string;
  name: string;
  description: string | null;
  trigger_type: string;
  trigger_config: Record<string, unknown>;
  steps: WorkflowStep[];
  graph?: WorkflowGraph | null;
  graph_source?: string;
  workflow_version?: number;
  status: string;
  editor_state?: { mode?: string; config_level?: string };
  hook_url?: string;
  has_hook_secret?: boolean;
};

export type WorkflowRun = {
  id: string;
  workflow_id: string;
  workflow_name?: string;
  status: string;
  started_at: string;
  duration_ms: number | null;
  error: string | null;
  simulate?: boolean;
};

export type WorkflowVersion = {
  id: string;
  workflow_id: string;
  version_number: number;
  status: string;
  notes: string | null;
  created_at: string;
  config_snapshot?: Record<string, unknown>;
};

export type KbOption = { id: string; name: string };
export type AgentOption = { id: string; name: string };

/** Badges compartidos por lista, estudio y panel de runs. */
export const STATUS_BADGE: Record<string, string> = {
  succeeded: "badge-ok",
  failed: "badge-danger",
  running: "badge-warning",
  paused: "badge-warning",
  skipped: "badge-muted",
  draft: "badge-muted",
  ready: "badge-info",
  production: "badge-ok",
  archived: "badge-muted",
  active: "badge-ok",
  simulated: "badge-info",
  pending_approval: "badge-warning",
};

/**
 * El estudio ya no tiene pestañas: el canvas y el dock de prueba viven juntos.
 * API y Avanzado se abren como drawers desde la cabecera, y `?panel=` sigue
 * siendo el deep-link que usa la lista de workflows.
 */
export const STUDIO_DRAWERS = ["api", "advanced"] as const;
export type StudioDrawer = (typeof STUDIO_DRAWERS)[number];

export const STUDIO_DRAWER_LABELS: Record<StudioDrawer, string> = {
  api: "API",
  advanced: "Avanzado",
};

export function isStudioDrawer(value: string | null): value is StudioDrawer {
  return value != null && (STUDIO_DRAWERS as readonly string[]).includes(value);
}

export type NormalizedPayload = {
  payload: Record<string, unknown>;
  /** true cuando el texto no era un objeto JSON y se envolvió como mensaje. */
  wrapped: boolean;
};

/**
 * Convierte lo que el usuario escribe en el campo de prueba a un payload de
 * trigger. Un objeto JSON pasa tal cual; cualquier otra cosa (texto suelto,
 * `{quien es el gerente}`, un número) se envuelve en `message`/`query` para que
 * `{{trigger.message}}` llegue a los nodos llm / kb_query.
 */
export function normalizeTestPayload(raw: string): NormalizedPayload {
  const text = (raw ?? "").trim();
  if (!text) return { payload: {}, wrapped: false };
  try {
    const parsed = JSON.parse(text);
    if (parsed && typeof parsed === "object" && !Array.isArray(parsed)) {
      return { payload: parsed as Record<string, unknown>, wrapped: false };
    }
  } catch {
    // texto libre: se envuelve abajo
  }
  return { payload: { message: text, query: text }, wrapped: true };
}

export type RunStepLike = {
  node_id?: string | null;
  node_type?: string | null;
  status: string;
  output?: Record<string, unknown>;
  error?: string | null;
};

export type ChatAnswer = {
  /** Texto que se muestra como burbuja del agente. */
  text: string;
  node_id: string | null;
  /** true cuando el nodo `llm` corrió sin agente y devolvió un eco. */
  echo: boolean;
  error: string | null;
};

/**
 * Extrae la respuesta legible de un run: el `output.text` del último nodo que
 * lo produjo, o el primer error. Sin esto el usuario solo ve JSON.
 */
export function answerFromSteps(steps: RunStepLike[] | undefined): ChatAnswer | null {
  const list = steps ?? [];
  const failed = list.find((s) => s.status === "failed" || s.status === "denied");
  if (failed) {
    return {
      text: failed.error || "El paso falló sin mensaje.",
      node_id: failed.node_id ?? null,
      echo: false,
      error: failed.error || "fallo sin mensaje",
    };
  }
  for (let i = list.length - 1; i >= 0; i -= 1) {
    const s = list[i];
    const out = s.output ?? {};
    const text = typeof out.text === "string" ? out.text : "";
    if (text.trim()) {
      return { text, node_id: s.node_id ?? null, echo: out.echo === true, error: null };
    }
  }
  const answered = list.find((s) => typeof (s.output ?? {}).answer === "string");
  if (answered) {
    return {
      text: String((answered.output ?? {}).answer ?? ""),
      node_id: answered.node_id ?? null,
      echo: false,
      error: null,
    };
  }
  return null;
}

/** Snippet curl del hook inbound. */
export function hookCurl(hookUrl: string, secret: string): string {
  return [
    `curl -X POST '${hookUrl}' \\`,
    `  -H 'Content-Type: application/json' \\`,
    `  -H 'X-Zent-Workflow-Secret: ${secret}' \\`,
    `  -d '{"message": "quien es el gerente"}'`,
  ].join("\n");
}

/** Snippet fetch del hook inbound. */
export function hookFetch(hookUrl: string, secret: string): string {
  return [
    `await fetch("${hookUrl}", {`,
    `  method: "POST",`,
    `  headers: {`,
    `    "Content-Type": "application/json",`,
    `    "X-Zent-Workflow-Secret": "${secret}",`,
    `  },`,
    `  body: JSON.stringify({ message: "quien es el gerente" }),`,
    `});`,
  ].join("\n");
}
