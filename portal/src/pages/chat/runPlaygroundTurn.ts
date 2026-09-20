import { api, type Session } from "../../api";
import { sourceIdsFromSteps, toolErrorsFromSteps } from "../../components/agentStudio/types";
import type { RunDetail } from "../../components/WorkflowRunInspector";
import { answerFromSteps } from "../../components/workflowStudio/types";
import type { PlaygroundTarget } from "./playgroundTargets";

export type PlaygroundSource = { text: string; image?: string; score?: number };

export type PlaygroundTurnResult = {
  text: string;
  sources?: PlaygroundSource[];
  sqlQuery?: string | null;
  method: string;
  lazyIngested?: boolean;
  queryId?: string;
  conversationId?: string;
  latencyMs?: number;
  stopped?: boolean;
  error?: string;
  ragTrace?: Record<string, unknown> | null;
  flow?: Record<string, unknown> | null;
};

export type StreamHooks = {
  onDelta?: (text: string) => void;
  onPhase?: (phase: string) => void;
  signal?: AbortSignal;
};

type Auth = { token: string; organizationId: string };

type TimelineStep = { name: string; status: string; ms: number; detail: string };

const AGENT_STEP_LABEL: Record<string, string> = {
  llm: "LLM (razonamiento)",
  tool_call: "Herramienta",
  tool_routing: "JEV elige herramienta",
  termination_gate: "JEV verifica cierre",
  answer_gate: "JEV verifica respuesta",
  answer_revision: "Revisión con feedback de JEV",
  final: "Respuesta final",
  guardrail: "Límite",
  error: "Error",
};

const GATE_VERDICT_LABEL: Record<string, string> = {
  approve: "aprobada",
  revise: "revisar",
  revise_exhausted: "aprobada (revisión ya usada)",
  abstain: "abstención",
};

export function flowFromAgentSteps(
  steps: unknown,
  totalMs: number,
  totals: { model?: string | null; cost?: number | null; totalTokens?: number | null } = {},
): Record<string, unknown> {
  const list = Array.isArray(steps)
    ? steps.filter(
        (step): step is Record<string, unknown> => typeof step === "object" && step !== null,
      )
    : [];
  let tokens = 0;
  let generationMs = 0;
  let jevUsed = false;
  let jevScore: number | null = null;
  let jevVerdict: string | null = null;
  let jevGrounded: boolean | null = null;
  let jevComplete: boolean | null = null;
  const timeline: TimelineStep[] = list.map((step) => {
    const type = String(step.type || "");
    if (type === "tool_routing" || type === "termination_gate" || type === "answer_gate") {
      jevUsed = true;
    }
    tokens += Number(step.tokens || 0);
    if (type === "llm") generationMs += Number(step.latency_ms || 0);
    let detail: string;
    if (type === "tool_routing") {
      const choice = step.choice ? String(step.choice) : "";
      const confidence = Number(step.confidence || 0);
      const score = Number(step.score || 0);
      detail = [
        choice || "—",
        confidence > 0 ? `confianza ${confidence.toFixed(2)}` : "",
        score > 0 ? `score ${score.toFixed(2)}` : "",
        step.certain === false ? "sin certeza (decide el LLM)" : "",
      ]
        .filter(Boolean)
        .join(" · ");
    } else if (type === "answer_gate") {
      const verdict = GATE_VERDICT_LABEL[String(step.verdict || "")] || String(step.verdict || "");
      detail = [
        step.grounded === true
          ? "respaldada"
          : step.grounded === false
            ? "sin respaldo"
            : "",
        step.complete === true
          ? "completa"
          : step.complete === false
            ? "incompleta"
            : "",
        Number(step.quality || 0) > 0 ? `calidad ${Number(step.quality)}/3` : "",
        verdict ? `→ ${verdict}` : "",
        Number(step.score || 0) > 0 ? `score ${Number(step.score).toFixed(2)}` : "",
      ]
        .filter(Boolean)
        .join(" · ");
      const score = Number(step.score || 0);
      if (score > 0) jevScore = score;
      if (step.verdict) jevVerdict = String(step.verdict);
      if (typeof step.grounded === "boolean") jevGrounded = step.grounded;
      if (typeof step.complete === "boolean") jevComplete = step.complete;
    } else if (type === "termination_gate") {
      detail = step.stop ? "cerró el run" : "continuó";
    } else if (type === "answer_revision") {
      detail = String(step.feedback || "corrección pedida por JEV").slice(0, 200);
    } else if (type === "tool_call") {
      detail = step.error
        ? String(step.error).slice(0, 160)
        : step.output
          ? String(step.output).slice(0, 120)
          : "herramienta";
    } else if (type === "llm") {
      detail = [
        step.model ? String(step.model) : "",
        Number(step.tokens || 0) > 0 ? `${Number(step.tokens)} tokens` : "",
        step.action ? Object.keys(step.action as object).join(", ") : "",
      ]
        .filter(Boolean)
        .join(" · ");
    } else {
      detail = String(step.detail || step.status || "").slice(0, 160);
    }
    return {
      name:
        type === "tool_call"
          ? String(step.tool || "herramienta")
          : AGENT_STEP_LABEL[type] || type || "paso",
      status: step.error ? "warn" : step.verdict === "abstain" ? "warn" : "ok",
      ms: Number(step.latency_ms || 0),
      detail,
    };
  });
  const totalTokens = Number(totals.totalTokens || 0) || tokens;
  const cost = typeof totals.cost === "number" ? totals.cost : null;
  return {
    method: "agent",
    verdict: { decider: "Agente", route: "Herramientas" },
    decision: {
      evaluated: true,
      provider: "agent",
      capability: null,
      confidence: 0,
      fallback_used: false,
      acting: true,
      mode: jevUsed ? "ReAct + JEV" : "ReAct",
    },
    jev: {
      used: jevUsed,
      score: jevScore,
      verdict: jevVerdict,
      grounded: jevGrounded,
      complete: jevComplete,
    },
    generation: {
      model: totals.model ?? null,
      total_tokens: totalTokens,
      ms: generationMs,
      cost,
    },
    steps: timeline,
    timings: { total_ms: totalMs, generation_ms: generationMs },
    fallbacks: [],
  };
}

function flowFromWorkflowSteps(
  steps: { step_type?: string; node_id?: string | null; node_type?: string | null; status?: string; error?: string | null; duration_ms?: number | null }[],
  totalMs: number,
): Record<string, unknown> {
  const timeline: TimelineStep[] = (steps || []).map((step) => ({
    name: String(step.node_type || step.step_type || step.node_id || "nodo"),
    status: step.status === "failed" || step.status === "denied" ? "warn" : "ok",
    ms: Number(step.duration_ms || 0),
    detail: step.error ? String(step.error).slice(0, 160) : String(step.status || ""),
  }));
  return {
    method: "workflow",
    verdict: { decider: "Workflow", route: "Nodos" },
    steps: timeline,
    timings: { total_ms: totalMs },
    fallbacks: [],
  };
}

async function httpError(res: Response): Promise<Error> {
  let message = `HTTP ${res.status}`;
  try {
    const data = (await res.json()) as { detail?: string; message?: string };
    message = data.detail || data.message || message;
  } catch {
    // keep HTTP status
  }
  return new Error(typeof message === "string" ? message : "Error al ejecutar");
}

async function readSse(
  res: Response,
  onEvent: (event: string, data: string) => void,
  signal?: AbortSignal,
): Promise<void> {
  if (!res.body) throw new Error("El servidor no envió un cuerpo");
  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  for (;;) {
    if (signal?.aborted) throw new DOMException("Aborted", "AbortError");
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    let idx: number;
    while ((idx = buffer.indexOf("\n\n")) !== -1) {
      const frame = buffer.slice(0, idx);
      buffer = buffer.slice(idx + 2);
      let event = "message";
      let data = "";
      for (const line of frame.split("\n")) {
        if (line.startsWith("event: ")) event = line.slice(7).trim();
        else if (line.startsWith("data: ")) data += line.slice(6);
      }
      if (data) onEvent(event, data);
    }
  }
}

export async function runKnowledgeTurn(input: {
  query: string;
  role: "admin" | "customer";
  conversationId: string | null;
  auth: Auth;
  hooks?: StreamHooks;
}): Promise<PlaygroundTurnResult> {
  const body: Record<string, unknown> = { query: input.query, role: input.role };
  if (input.conversationId) body.conversation_id = input.conversationId;

  const res = await fetch("/api/v1/rag/query/stream", {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      Authorization: `Bearer ${input.auth.token}`,
      "X-Organization-Id": input.auth.organizationId,
      "X-User-Role": input.role,
    },
    body: JSON.stringify(body),
    signal: input.hooks?.signal,
  });
  if (!res.ok) throw await httpError(res);

  let acc = "";
  let sources: PlaygroundSource[] = [];
  let sqlQuery: string | null = null;
  let method = "rag";
  let lazyIngested = false;
  let queryId = "";
  let conversationId = input.conversationId ?? "";
  let latencyMs = 0;
  let sawMeta = false;
  let ragTrace: Record<string, unknown> | null = null;
  let flow: Record<string, unknown> | null = null;

  await readSse(
    res,
    (event, data) => {
      if (event === "delta") {
        const text = (JSON.parse(data) as { text: string }).text;
        acc += text;
        input.hooks?.onDelta?.(acc);
        input.hooks?.onPhase?.("");
      } else if (event === "sources") {
        sawMeta = true;
        const payload = JSON.parse(data) as {
          sources: ({ content?: string; score?: number; image_base64?: string | null } | string)[];
          method: string;
          sql_query: string | null;
          lazy_ingested: boolean;
        };
        method = payload.method;
        sqlQuery = payload.sql_query ?? null;
        lazyIngested = payload.lazy_ingested ?? false;
        sources =
          payload.method === "sql"
            ? []
            : (payload.sources || [])
                .filter(
                  (s): s is { content?: string; score?: number; image_base64?: string | null } =>
                    typeof s === "object" && s !== null,
                )
                .slice(0, 6)
                .map((s) => ({
                  text: (s.content || "").slice(0, 240),
                  image: s.image_base64 || undefined,
                  score: s.score,
                }));
      } else if (event === "done") {
        const payload = JSON.parse(data) as {
          conversation_id: string;
          query_id: string;
          latency_ms: number;
          rag_trace?: Record<string, unknown> | null;
          flow?: Record<string, unknown> | null;
        };
        queryId = payload.query_id;
        conversationId = payload.conversation_id;
        latencyMs = payload.latency_ms ?? 0;
        ragTrace = payload.rag_trace ?? null;
        flow = payload.flow ?? null;
      } else if (event === "error") {
        throw new Error((JSON.parse(data) as { message: string }).message);
      }
    },
    input.hooks?.signal,
  );

  if (!sawMeta && !acc) {
    throw new Error("El servidor cerró la conexión sin enviar una respuesta");
  }
  return {
    text: acc,
    sources: sources.length > 0 ? sources : undefined,
    sqlQuery,
    method,
    lazyIngested,
    queryId,
    conversationId,
    latencyMs,
    ragTrace,
    flow,
  };
}

export async function runAgentTurn(input: {
  agentId: string;
  message: string;
  conversationId: string | null;
  auth: Auth;
  hooks?: StreamHooks;
}): Promise<PlaygroundTurnResult> {
  input.hooks?.onPhase?.("Ejecutando agente…");
  const body: Record<string, unknown> = { message: input.message };
  if (input.conversationId) body.conversation_id = input.conversationId;

  const res = await fetch(`/api/v1/agents/${input.agentId}/run/stream`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      Authorization: `Bearer ${input.auth.token}`,
      "X-Organization-Id": input.auth.organizationId,
      "Idempotency-Key": crypto.randomUUID(),
    },
    body: JSON.stringify(body),
    signal: input.hooks?.signal,
  });
  if (!res.ok) throw await httpError(res);

  let answer = "";
  let latencyMs = 0;
  let used: string[] = [];
  let errors: string[] = [];
  let steps: unknown = [];
  let model: string | null = null;
  let cost: number | null = null;
  let totalTokens: number | null = null;

  await readSse(
    res,
    (event, data) => {
      const payload = JSON.parse(data) as {
        phase?: string;
        answer?: string;
        status?: string;
        message?: string;
        steps?: unknown;
        total_latency_ms?: number;
        total_tokens?: number;
        cost?: number;
        model?: string | null;
      };
      if (event === "status") {
        input.hooks?.onPhase?.(payload.phase === "running" ? "Ejecutando agente…" : "En curso…");
      } else if (event === "done") {
        answer = payload.answer || "";
        used = sourceIdsFromSteps(payload.steps);
        errors = toolErrorsFromSteps(payload.steps);
        steps = payload.steps;
        latencyMs = payload.total_latency_ms ?? 0;
        model = payload.model ?? null;
        cost = typeof payload.cost === "number" ? payload.cost : null;
        totalTokens = typeof payload.total_tokens === "number" ? payload.total_tokens : null;
        input.hooks?.onDelta?.(answer);
        input.hooks?.onPhase?.("");
      } else if (event === "error") {
        throw new Error(payload.message || "Error en el stream");
      }
    },
    input.hooks?.signal,
  );

  return {
    text: answer || "(sin respuesta)",
    sources: used.length > 0 ? used.map((id) => ({ text: id })) : undefined,
    method: "agent",
    conversationId: input.conversationId ?? undefined,
    latencyMs,
    error: errors[0],
    flow: flowFromAgentSteps(steps, latencyMs, { model, cost, totalTokens }),
  };
}

export async function runWorkflowTurn(input: {
  workflowId: string;
  message: string;
  session: Session;
  hooks?: StreamHooks;
}): Promise<PlaygroundTurnResult> {
  input.hooks?.onPhase?.("Simulando el flujo…");
  const out = await api<{ run_id: string; status: string }>(`/api/v1/workflows/${input.workflowId}/run`, {
    method: "POST",
    token: input.session.token,
    organizationId: input.session.organizationId,
    body: JSON.stringify({ payload: { message: input.message }, simulate: true }),
  });
  const detail = await api<RunDetail>(`/api/v1/workflows/runs/${out.run_id}`, {
    token: input.session.token,
    organizationId: input.session.organizationId,
  });
  const answer = answerFromSteps(detail.steps);
  const text =
    answer?.text ||
    (detail.error ? String(detail.error) : "El flujo terminó sin un texto de respuesta.");
  input.hooks?.onDelta?.(text);
  input.hooks?.onPhase?.("");
  return {
    text,
    method: "workflow",
    latencyMs: detail.duration_ms ?? 0,
    error: answer?.error || undefined,
    flow: flowFromWorkflowSteps(detail.steps || [], detail.duration_ms ?? 0),
  };
}

export async function runPlaygroundTurn(input: {
  target: PlaygroundTarget;
  query: string;
  role: "admin" | "customer";
  conversationId: string | null;
  session: Session;
  hooks?: StreamHooks;
}): Promise<PlaygroundTurnResult> {
  const auth = { token: input.session.token || "", organizationId: input.session.organizationId };
  if (input.target.kind === "agent") {
    return runAgentTurn({
      agentId: input.target.id,
      message: input.query,
      conversationId: input.conversationId,
      auth,
      hooks: input.hooks,
    });
  }
  if (input.target.kind === "workflow") {
    return runWorkflowTurn({
      workflowId: input.target.id,
      message: input.query,
      session: input.session,
      hooks: input.hooks,
    });
  }
  return runKnowledgeTurn({
    query: input.query,
    role: input.role,
    conversationId: input.conversationId,
    auth,
    hooks: input.hooks,
  });
}
