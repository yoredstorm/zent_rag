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
};

export type StreamHooks = {
  onDelta?: (text: string) => void;
  onPhase?: (phase: string) => void;
  signal?: AbortSignal;
};

type Auth = { token: string; organizationId: string };

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
        };
        queryId = payload.query_id;
        conversationId = payload.conversation_id;
        latencyMs = payload.latency_ms ?? 0;
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
      };
      if (event === "status") {
        input.hooks?.onPhase?.(payload.phase === "running" ? "Ejecutando agente…" : "En curso…");
      } else if (event === "done") {
        answer = payload.answer || "";
        used = sourceIdsFromSteps(payload.steps);
        errors = toolErrorsFromSteps(payload.steps);
        latencyMs = payload.total_latency_ms ?? 0;
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
