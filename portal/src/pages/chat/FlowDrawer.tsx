import { useEffect, useState } from "react";
import { api, type Session } from "../../api";
import { Badge, CodeBlock, Drawer, Skeleton } from "../../components/ui";
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
  question,
  session,
  onFetched,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  flow: Flow | null;
  role: "admin" | "customer";
  queryId?: string;
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

  useEffect(() => {
    if (!open || flow || !queryId) return;
    setLoading(true);
    setError("");
    api<{ flow: Flow }>(`/api/v1/rag/queries/${queryId}/flow`, {
      token: session.token,
      organizationId: session.organizationId,
    })
      .then((out) => {
        setFetched(out.flow);
        onFetched?.(out.flow);
      })
      .catch((err) => {
        const detail = err instanceof Error ? err.message : "";
        setError(
          detail
            ? `No se pudo cargar el flujo: ${detail}`
            : "No se pudo cargar el flujo",
        );
      })
      .finally(() => setLoading(false));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, flow, queryId]);

  useEffect(() => {
    if (!open || !queryId) {
      setImpact(null);
      setImpactState("idle");
      return;
    }
    let cancelled = false;
    setImpact(null);
    setImpactState("loading");
    api<QueryImpact>(`/api/v1/memory/queries/${queryId}/impact`, {
      token: session.token,
      organizationId: session.organizationId,
    })
      .then((body) => {
        if (cancelled) return;
        if (!body?.counts) {
          setImpactState("error");
          return;
        }
        setImpact(body);
        setImpactState("ready");
      })
      .catch(() => {
        if (!cancelled) setImpactState("error");
      });
    return () => {
      cancelled = true;
    };
  }, [open, queryId, session.token, session.organizationId]);

  useEffect(() => {
    setReplay(null);
    setReplayError("");
    setReplayPending(false);
  }, [open, queryId]);

  function runReplay() {
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
