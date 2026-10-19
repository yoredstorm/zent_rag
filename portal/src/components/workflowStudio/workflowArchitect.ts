/**
 * Cliente y contrato del Workflow Architect (camino canónico).
 *
 * La UI NO interpreta la respuesta como un WorkflowPlan legacy ni compila
 * grafos: envía el plan al backend y este re-valida, compila y persiste.
 */
import { api, type Session } from "../../api";

export const DESIGN_STATES = [
  "UNDERSTANDING",
  "DISCOVERING",
  "PLANNING",
  "NEEDS_CLARIFICATION",
  "NEEDS_CONFIGURATION",
  "VALIDATING",
  "DRAFT_READY",
  "BLOCKED",
] as const;

export type DesignState = (typeof DESIGN_STATES)[number];

export type ArchitectIssue = {
  code: string;
  severity: "error" | "warning" | "info";
  message: string;
  hint?: string | null;
  requirement?: string | null;
  step_id?: string | null;
};

export type ArchitectClarification = {
  question: string;
  impact: "high" | "medium" | "low" | string;
  code: string;
  step_id?: string | null;
};

export type ArchitectRequirement = {
  requirement: string;
  code: string;
  message: string;
  resolved: boolean;
};

export type ArchitectBlocker = {
  kind: "requirement" | "issue" | "readiness" | string;
  code: string;
  message: string;
  requirement?: string | null;
};

export type ArchitectPreviewItem = {
  kind: string;
  step_id: string;
  text: string;
};

export type ArchitectPhase = { name: string; duration_ms: number };

export type ArchitectFallback = {
  used: boolean;
  reason_code: string;
  limitations: string[];
  requires_review: boolean;
  publishable: boolean;
  preserved_requirement: string;
};

export type ArchitectGraphNode = {
  id: string;
  type: string;
  label?: string;
  config?: Record<string, unknown>;
};

export type ArchitectGraph = {
  workflow_version?: number;
  nodes: ArchitectGraphNode[];
  edges?: { from_node: string; from_port?: string; to_node: string }[];
  entrypoints?: string[];
  metadata?: Record<string, unknown>;
};

export type ArchitectReadiness = {
  ready: boolean;
  passed: number;
  warnings: number;
  errors: number;
  total: number;
  checks?: { key: string; label: string; status: string; message: string }[];
};

export type ArchitectCost = {
  per_run: number;
  monthly: number;
  calls_per_run: number;
  ai_calls_per_run: number;
  currency: string;
  warnings?: { code: string; message: string }[];
};

export type ArchitectProposal = {
  session_id: string;
  state: DesignState;
  planner: {
    version: string;
    provider: string | null;
    model: string | null;
    source: "llm" | "heuristics";
  };
  phases: ArchitectPhase[];
  fallback: ArchitectFallback | null;
  plan_hash: string;
  publishable: boolean;
  blockers: ArchitectBlocker[];
  source: "llm" | "heuristics";
  intent: Record<string, unknown> | null;
  plan: Record<string, unknown>;
  issues: ArchitectIssue[];
  preview: ArchitectPreviewItem[];
  graph: ArchitectGraph | null;
  steps_map?: Record<string, string>;
  cost: ArchitectCost | null;
  assumptions: { statement: string; impact: string; needs_confirmation: boolean }[];
  questions: string[];
  clarifications: ArchitectClarification[];
  requirements: ArchitectRequirement[];
  readiness: ArchitectReadiness | null;
  simulation: { step_id: string; goal: string; expectation: string; effects: string }[] | null;
  notes: string[];
  patch?: {
    summary?: string;
    operations?: { kind: string; reason?: string }[];
  };
};

export type ArchitectConfig = {
  enabled: boolean;
  planner_version: string;
  states: DesignState[];
};

export type DraftSaveResult = {
  workflow_id: string;
  name: string;
  workflow_version?: number;
  hook_secret?: string;
  state: DesignState;
  session_id: string;
  plan_hash: string;
  requirements: ArchitectRequirement[];
  readiness: ArchitectReadiness | null;
  blockers: ArchitectBlocker[];
  publishable: boolean;
  source: "llm" | "heuristics";
};

function auth(session: Session) {
  return { token: session.token, organizationId: session.organizationId };
}

/** Config del feature flag. Ante fallo, el portal usa el camino legacy. */
export async function fetchArchitectConfig(session: Session): Promise<ArchitectConfig | null> {
  try {
    return await api<ArchitectConfig>("/api/v1/workflows/architect/config", auth(session));
  } catch {
    return null;
  }
}

export async function planWithArchitect(
  session: Session,
  prompt: string,
  sessionId?: string,
  agentId?: string,
): Promise<ArchitectProposal> {
  return api<ArchitectProposal>("/api/v1/workflows/architect/plan", {
    method: "POST",
    ...auth(session),
    body: JSON.stringify({
      prompt,
      session_id: sessionId,
      agent_id: agentId || undefined,
    }),
  });
}

export async function patchArchitectPlan(
  session: Session,
  input: {
    plan: Record<string, unknown>;
    instruction: string;
    sessionId: string;
    planHash: string;
  },
): Promise<ArchitectProposal> {
  return api<ArchitectProposal>("/api/v1/workflows/architect/patch", {
    method: "POST",
    ...auth(session),
    body: JSON.stringify({
      plan: input.plan,
      instruction: input.instruction,
      session_id: input.sessionId,
      plan_hash: input.planHash,
    }),
  });
}

export async function saveArchitectDraft(
  session: Session,
  input: {
    proposal: ArchitectProposal;
    name: string;
    description: string;
    configLevel: "simple" | "advanced";
  },
): Promise<DraftSaveResult> {
  return api<DraftSaveResult>("/api/v1/workflows/architect/draft", {
    method: "POST",
    ...auth(session),
    body: JSON.stringify({
      plan: input.proposal.plan,
      plan_hash: input.proposal.plan_hash,
      session_id: input.proposal.session_id,
      name: input.name,
      description: input.description,
      source: input.proposal.planner.source,
      editor_state: { mode: "canvas", config_level: input.configLevel },
    }),
  });
}

export const STATE_LABEL: Record<DesignState, string> = {
  UNDERSTANDING: "Entendiendo el pedido",
  DISCOVERING: "Revisando tus capacidades",
  PLANNING: "Diseñando el proceso",
  NEEDS_CLARIFICATION: "Necesito que confirmes algo",
  NEEDS_CONFIGURATION: "Faltan dependencias",
  VALIDATING: "Validando el diseño",
  DRAFT_READY: "Borrador listo para revisar",
  BLOCKED: "No se pudo diseñar todavía",
};

export const PREVIEW_LABEL: Record<string, string> = {
  when: "CUANDO",
  get: "OBTENER",
  consult: "CONSULTAR",
  analyze: "ANALIZAR",
  if: "DECIDIR",
  then: "DESPUÉS",
  after: "AL FINAL",
};
