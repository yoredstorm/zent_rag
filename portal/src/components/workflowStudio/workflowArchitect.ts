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

export type ArchitectMatch = {
  need: string;
  capability_ref: string;
  version?: number | null;
  reason?: string;
  availability?: string | null;
  bindings?: string[];
  unresolved?: string[];
  alternatives?: string[];
};

export type ArchitectTraceStage = {
  name: string;
  duration_ms: number;
  detail?: string;
};

export type ArchitectToolCall = {
  tool: string;
  arguments?: Record<string, unknown>;
  ok: boolean;
  error?: string | null;
  duration_ms?: number;
  result_hash?: string | null;
  result_summary?: string | null;
};

export type ArchitectTrace = {
  path: string[];
  stages: ArchitectTraceStage[];
  tool_calls: ArchitectToolCall[];
  repair_attempts: number;
};

export type ArchitectUsage = {
  llm_calls: number;
  tool_calls: number;
  prompt_tokens: number;
  completion_tokens: number;
  total_tokens: number;
  estimated_cost_usd: number;
  duration_ms: number;
  repairs: number;
  cancelled: boolean;
};

export type ArchitectResourceResolution = {
  schema_id?: string;
  need?: string;
  resolved?: boolean;
  selected?: {
    resource_ref?: string;
    display_name?: string;
    kind?: string;
    resource_class?: string;
  } | null;
  unresolved?: { code?: string; message?: string; fields?: string[] }[];
  bindings?: {
    capability_ref?: string;
    availability?: string;
    binding_found?: boolean;
    provider_kind?: string | null;
  }[];
  guided_configuration?: {
    code?: string;
    title?: string;
    reason?: string;
    module?: string;
  }[];
  trace?: Record<string, unknown>;
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

export type CapabilitySnapshotSummary = {
  snapshot_hash: string;
  generated_at: string;
  catalog_version?: number;
  counts?: { capabilities?: number; resources?: number; events?: number };
  coverage?: {
    total_capabilities?: number;
    business_capabilities?: number;
    business_complete?: number;
    business_completeness?: number;
  };
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
  plan_hash: string | null;
  publishable: boolean;
  blockers: ArchitectBlocker[];
  source: "llm" | "heuristics";
  mode?: "agentic" | string;
  intent: Record<string, unknown> | null;
  plan: Record<string, unknown> | null;
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
  simulation_preview?: { step_id: string; goal: string; expectation: string; effects: string }[] | null;
  capability_snapshot?: CapabilitySnapshotSummary | null;
  specification?: Record<string, unknown> | null;
  matches?: ArchitectMatch[];
  trace?: ArchitectTrace;
  usage?: ArchitectUsage;
  resource_resolution?: ArchitectResourceResolution | null;
  requires_durable_instance?: boolean;
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
  return api<ArchitectProposal>("/api/v1/workflows/architect/agentic-plan", {
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
      capability_snapshot_hash: input.proposal.capability_snapshot?.snapshot_hash,
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
