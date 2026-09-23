import { useEffect, useMemo, useState } from "react";
import { api, type Session } from "../../api";
import { Badge, CodeBlock, Drawer, Skeleton } from "../../components/ui";
import {
  executionFlowPath,
  executionRefOf,
  memoryImpactPath,
  normalizeRunImpact,
  type ExecutionRef,
} from "./executionRef";
import { buildExecutionStory } from "./executionStory";
import type { ImpactLoad, QueryImpact } from "./MemoryImpact";
import type { ReplayResult } from "./ReplayCompare";
import { ExecutionStoryView, type StoryMode } from "./story/ExecutionStoryView";

type Flow = Record<string, unknown>;

export default function FlowDrawer({
  open,
  onOpenChange,
  flow,
  role,
  queryId,
  runId,
  method,
  executionRef,
  question,
  session,
  onFetched,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  flow: Flow | null;
  role: "admin" | "customer";
  queryId?: string;
  /** Run del agente/workflow: referencia de ejecución cuando no hay query_id. */
  runId?: string;
  method?: string;
  /** Referencia explícita; si falta se deriva de queryId/runId. */
  executionRef?: ExecutionRef | null;
  question?: string;
  session: Session;
  onFetched?: (flow: Flow) => void;
}) {
  const [fetched, setFetched] = useState<Flow | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [impact, setImpact] = useState<QueryImpact | null>(null);
  const [impactState, setImpactState] = useState<ImpactLoad>("idle");
  const [replay, setReplay] = useState<ReplayResult | null>(null);
  const [replayError, setReplayError] = useState("");
  const [replayPending, setReplayPending] = useState(false);
  // La historia es el modo por defecto para todos los roles (§32).
  const [mode, setMode] = useState<StoryMode>("story");

  const ref = useMemo(
    () => executionRef ?? executionRefOf({ queryId, runId, method }) ?? null,
    [executionRef, queryId, runId, method],
  );

  useEffect(() => {
    if (!open || flow || !ref) return;
    setLoading(true);
    setError("");
    api<{ flow: Flow | null }>(executionFlowPath(ref), {
      token: session.token,
      organizationId: session.organizationId,
    })
      .then((out) => {
        if (!out.flow) {
          setError("Esta ejecución no tiene un flujo guardado.");
          return;
        }
        setFetched(out.flow);
        onFetched?.(out.flow);
      })
      .catch((err) => {
        const detail = err instanceof Error ? err.message : "";
        setError(
          detail ? `No se pudo cargar el flujo: ${detail}` : "No se pudo cargar el flujo",
        );
      })
      .finally(() => setLoading(false));
    // Sólo se recarga cuando cambia la ejecución o falta el flow: `onFetched`
    // es un callback del padre y no debe re-disparar el fetch.
    // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [open, flow, ref]);

  useEffect(() => {
    if (!open || !ref) {
      setImpact(null);
      setImpactState("idle");
      return;
    }
    const path = memoryImpactPath(ref);
    if (!path) {
      // Sin integración de memoria para este tipo: se dice, no se muestra 0.
      setImpact(null);
      setImpactState("unavailable");
      return;
    }
    let cancelled = false;
    setImpact(null);
    setImpactState("loading");
    api<unknown>(path, {
      token: session.token,
      organizationId: session.organizationId,
    })
      .then((body) => {
        if (cancelled) return;
        const normalized = normalizeRunImpact(body, ref);
        if (!normalized) {
          setImpactState("error");
          return;
        }
        setImpact(normalized);
        setImpactState("ready");
      })
      .catch(() => {
        if (!cancelled) setImpactState("error");
      });
    return () => {
      cancelled = true;
    };
  }, [open, ref, session.token, session.organizationId]);

  useEffect(() => {
    setReplay(null);
    setReplayError("");
    setReplayPending(false);
  }, [open, ref]);

  function runReplay() {
    // El replay existe sólo para respuestas RAG (query_id): no se inventa para
    // runs de agente.
    if (!queryId || replayPending) return;
    setReplayPending(true);
    setReplayError("");
    api<ReplayResult>(`/api/v1/memory/queries/${queryId}/replay`, {
      method: "POST",
      body: JSON.stringify({ question: question ?? "", tools: [] }),
      token: session.token,
      organizationId: session.organizationId,
    })
      .then((body) => {
        if (!body?.comparison?.fields) {
          setReplayError("No se pudo comparar esta respuesta.");
          return;
        }
        setReplay(body);
      })
      .catch((err) => {
        const message = err instanceof Error ? err.message : "";
        setReplayError(message || "No se pudo reejecutar esta respuesta.");
      })
      .finally(() => setReplayPending(false));
  }

  const active = flow ?? fetched;
  const story = active ? buildExecutionStory(active) : null;
  const sql = active?.sql ? (active.sql as Flow) : null;
  const memoryHits = countMemoryHits(active);

  return (
    <Drawer
      open={open}
      onOpenChange={onOpenChange}
      title="Ver flujo"
      description="La historia auditable de cómo Zent llegó a esta respuesta."
    >
      {loading ? <Skeleton className="h-40" /> : null}
      {error ? <p className="text-[13px] text-danger">{error}</p> : null}
      {!loading && !error && story ? (
        <ExecutionStoryView
          story={story}
          mode={mode}
          onModeChange={setMode}
          impact={impact}
          impactState={impactState}
          memoryHits={memoryHits}
          replay={replay}
          replayError={replayError}
          replayPending={replayPending}
          onReplay={runReplay}
          showReplay={Boolean(queryId)}
          sqlView={
            sql && role === "admin" ? (
              <section>
                <div className="mb-2 flex flex-wrap items-center gap-2">
                  <p className="eyebrow">SQL ejecutado</p>
                  <Badge tone="neutral">{Number(sql.rows ?? 0)} filas</Badge>
                </div>
                <CodeBlock code={String(sql.query ?? "")} language="sql" maxHeight={240} />
              </section>
            ) : null
          }
        />
      ) : null}
    </Drawer>
  );
}

function countMemoryHits(flow: Flow | null): number {
  if (!flow) return 0;
  const steps = Array.isArray(flow.steps)
    ? (flow.steps as Array<Record<string, unknown>>)
    : [];
  return steps.reduce((total, step) => {
    const hits = Number(step?.memory_hits ?? 0);
    return total + (Number.isFinite(hits) ? hits : 0);
  }, 0);
}
