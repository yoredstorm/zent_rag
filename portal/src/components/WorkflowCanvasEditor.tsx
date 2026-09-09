import { FloppyDisk, Play, Flask } from "@phosphor-icons/react";
import { useCallback, useEffect, useMemo, useState } from "react";
import { api } from "../api";
import { useAuth } from "../auth";
import type { WorkflowGraph } from "../lib/workflowGraph";
import { makeNode, prepareGraphForSave, triggerConfigOf, triggerTypeOf } from "../lib/workflowGraph";
import { NodeConfigPanel } from "./NodeConfigPanel";
import { NodeLibrary } from "./NodeLibrary";
import { WorkflowCanvas, type RunOverlay } from "./WorkflowCanvas";
import { WorkflowRunInspector, type RunDetail } from "./WorkflowRunInspector";
import { ErrorInline } from "./ui";

type Props = {
  workflowId: string | null;
  graph: WorkflowGraph | null;
  onChangeGraph: (g: WorkflowGraph, triggerType: "webhook" | "schedule" | "event", triggerConfig: Record<string, unknown>) => void;
  kbs: { id: string; name: string }[];
  agents: { id: string; name: string }[];
  onSaved?: (wf: { workflow_id: string }) => void;
  busyToken?: boolean;
};

export function WorkflowCanvasEditor({ workflowId, graph, onChangeGraph, kbs, agents, onSaved, busyToken }: Props) {
  const { session } = useAuth();
  const [selectedNode, setSelectedNode] = useState<string | null>(null);
  const [selectedEdge, setSelectedEdge] = useState<string | null>(null);
  const [busy, setBusy] = useState("");
  const [error, setError] = useState("");
  const [payload, setPayload] = useState("{}");
  const [run, setRun] = useState<RunDetail | null>(null);
  const [runResult, setRunResult] = useState<{ run_id: string; status: string; planned_effects?: unknown[]; result?: unknown } | null>(null);
  const [mxInstalls, setMxInstalls] = useState<{ id: string; integration: { slug: string; name: string } }[]>([]);
  const [mxActions, setMxActions] = useState<Record<string, { action_id: string; display_name: string }[]>>({});

  useEffect(() => {
    if (!session) return;
    api<{ installs: { id: string; integration: { slug: string; name: string } }[] }>(
      "/api/v1/integrations/installs",
      { token: session.token, organizationId: session.organizationId }
    )
      .then((d) => setMxInstalls(d.installs || []))
      .catch(() => undefined);
  }, [session, workflowId]);

  const ensureActions = useCallback(
    async (installId: string) => {
      if (!session || !installId || mxActions[installId]) return;
      const install = mxInstalls.find((i) => i.id === installId);
      if (!install) return;
      try {
        const m = await api<{ capabilities: { actions: { action_id: string; display_name: string }[] }[] }>(
          `/api/v1/integrations/catalog/${install.integration.slug}`,
          { token: session.token, organizationId: session.organizationId }
        );
        const actions = (m.capabilities ?? []).flatMap((c) => c.actions ?? []);
        setMxActions((prev) => ({ ...prev, [installId]: actions }));
      } catch {
        setMxActions((prev) => ({ ...prev, [installId]: [] }));
      }
    },
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [session, mxInstalls, mxActions]
  );

  useEffect(() => {
    if (selectedNode && graph) {
      const n = graph.nodes.find((x) => x.id === selectedNode);
      if (n?.type === "marketplace_action" && n.config.install_id) {
        void ensureActions(String(n.config.install_id));
      }
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedNode, graph]);

  useEffect(() => {
    setSelectedNode(null);
    setSelectedEdge(null);
    setRun(null);
    setRunResult(null);
  }, [workflowId]);

  const overlay: RunOverlay = useMemo(() => {
    const out: RunOverlay = {};
    for (const s of run?.steps ?? []) {
      if (s.node_id) {
        out[s.node_id] = {
          status: s.status,
          duration_ms: s.duration_ms,
          error: s.error,
          simulated: s.status === "simulated",
        };
      }
    }
    return out;
  }, [run]);

  const local = graph;

  function addNode(nodeType: string) {
    if (!graph || !workflowId) return;
    // posición: centro actual del canvas (simple: cascade)
    const count = graph.nodes.length;
    const n = makeNode(nodeType, { x: 40 + (count % 5) * 40, y: 60 + (count % 4) * 40 });
    const copy: WorkflowGraph = {
      ...graph,
      nodes: [...graph.nodes.map((x) => ({ ...x, config: { ...x.config } })), n],
      entrypoints: graph.entrypoints.length ? graph.entrypoints : [n.id],
    };
    onChangeGraph(copy, triggerTypeOf(copy), triggerConfigOf(copy));
    setSelectedNode(n.id);
  }

  function patch(updater: (g: WorkflowGraph) => WorkflowGraph) {
    if (!graph) return;
    const copy = updater(structuredClone(graph));
    onChangeGraph(copy, triggerTypeOf(copy), triggerConfigOf(copy));
  }

  async function save() {
    if (!session || !workflowId || !graph) return;
    setBusy("save");
    setError("");
    try {
      const g = prepareGraphForSave(graph);
      const ttype = triggerTypeOf(g);
      const tcfg = triggerConfigOf(g);
      await api(`/api/v1/workflows/${workflowId}`, {
        method: "PATCH",
        token: session.token,
        organizationId: session.organizationId,
        body: JSON.stringify({ graph: g, workflow_version: 2, trigger_config: tcfg }),
      });
      if (ttype === "event" && tcfg.event_type) {
        await api("/api/v1/workflows/triggers", {
          method: "POST",
          token: session.token,
          organizationId: session.organizationId,
          body: JSON.stringify({ workflow_id: workflowId, event_type: String(tcfg.event_type), filters: (tcfg.filters as Record<string, unknown>) ?? {} }),
        }).catch(() => undefined);
      }
      onSaved?.({ workflow_id: workflowId });
      setError("Guardado ✓");
    } catch (e) {
      setError(e instanceof Error ? e.message : "Error");
    } finally {
      setBusy("");
    }
  }

  async function testRun() {
    if (!session || !workflowId) return;
    setBusy("test");
    setError("");
    try {
      let p: Record<string, unknown> = {};
      try {
        p = JSON.parse(payload || "{}");
      } catch {
        setError("Payload JSON inválido");
        setBusy("");
        return;
      }
      const out = await api<{ run_id: string; status: string; planned_effects?: unknown[]; result?: unknown }>(
        `/api/v1/workflows/${workflowId}/run`,
        { method: "POST", token: session.token, organizationId: session.organizationId, body: JSON.stringify({ payload: p, simulate: true }) }
      );
      setRunResult(out);
      const detail = await api<RunDetail>(`/api/v1/workflows/runs/${out.run_id}`, { token: session.token, organizationId: session.organizationId });
      setRun(detail as RunDetail);
      setError(`Dry-run: ${out.status}`);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Error");
    } finally {
      setBusy("");
    }
  }

  async function runNow() {
    if (!session || !workflowId) return;
    setBusy("run");
    setError("");
    try {
      let p: Record<string, unknown> = {};
      try {
        p = JSON.parse(payload || "{}");
      } catch {
        setError("Payload JSON inválido");
        setBusy("");
        return;
      }
      const out = await api<{ run_id: string; status: string }>(`/api/v1/workflows/${workflowId}/run`, {
        method: "POST",
        token: session.token,
        organizationId: session.organizationId,
        body: JSON.stringify({ payload: p }),
      });
      setRunResult(null);
      const detail = await api<RunDetail>(`/api/v1/workflows/runs/${out.run_id}`, { token: session.token, organizationId: session.organizationId });
      setRun(detail as RunDetail);
      setError(`Run: ${out.status}`);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Error");
    } finally {
      setBusy("");
    }
  }

  const deleteNode = useCallback(
    (id: string) => {
      patch((g) => ({
        ...g,
        nodes: g.nodes.filter((n) => n.id !== id),
        edges: g.edges.filter((e) => e.from_node !== id && e.to_node !== id),
        entrypoints: g.entrypoints.filter((e) => e !== id),
      }));
      setSelectedNode(null);
    },
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [graph]
  );

  const deleteEdge = useCallback(
    (id: string) => {
      patch((g) => ({ ...g, edges: g.edges.filter((e) => e.id !== id) }));
      setSelectedEdge(null);
    },
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [graph]
  );

  const selectedNodeObj = local?.nodes.find((n) => n.id === selectedNode) ?? null;
  const selectedEdgeObj = local?.edges.find((e) => e.id === selectedEdge) ?? null;

  return (
    <div className="space-y-3" data-testid="workflow-canvas-editor">
      {error && <ErrorInline>{error}</ErrorInline>}

      {/* Toolbar */}
      <div className="flex flex-wrap items-center gap-2">
        <input
          className="w-48 rounded-md border border-border bg-soft px-2 py-1.5 font-mono text-[10px]"
          placeholder='{"stock": "3"}'
          value={payload}
          onChange={(e) => setPayload(e.target.value)}
          aria-label="Payload de ejecución"
        />
        <span className="flex-1" />
        <button type="button" className="btn btn-ghost min-h-8 px-2 text-[11px]" disabled={!workflowId || !!busy || busyToken} onClick={() => void save()} data-testid="wf-save">
          <FloppyDisk size={13} /> Guardar
        </button>
        <button type="button" className="btn btn-secondary min-h-8 px-2 text-[11px]" disabled={!workflowId || !!busy} onClick={() => void testRun()} data-testid="wf-test">
          <Flask size={13} /> Probar (dry-run)
        </button>
        <button type="button" className="btn btn-primary min-h-8 px-2 text-[11px]" disabled={!workflowId || !!busy} onClick={() => void runNow()} data-testid="wf-run">
          <Play size={13} /> Ejecutar
        </button>
      </div>

      {/* Editor: biblioteca | canvas | configuración */}
      <div className="flex gap-3">
        <NodeLibrary
          usedTypes={local ? local.nodes.map((n) => n.type) : []}
          onAdd={(meta) => addNode(meta.type)}
        />
        <div className="min-w-0 flex-1">
          {local ? (
            <WorkflowCanvas
              graph={local}
              onChange={(g) => {
                onChangeGraph(g, triggerTypeOf(g), triggerConfigOf(g));
              }}
              selectedNodeId={selectedNode}
              onSelectNode={setSelectedNode}
              selectedEdgeId={selectedEdge}
              onSelectEdge={setSelectedEdge}
              overlay={overlay}
            />
          ) : (
            <div className="flex h-[560px] w-full items-center justify-center rounded-md border border-dashed border-border bg-soft/30 text-xs text-faint">
              {workflowId ? "Cargando grafo…" : "Crea un workflow arriba o selecciona uno de la lista para editar su canvas."}
            </div>
          )}
        </div>
        {local ? (
          <NodeConfigPanel
            graph={local}
            node={selectedNodeObj}
            edge={selectedEdgeObj}
            onChange={(g) => onChangeGraph(g, triggerTypeOf(g), triggerConfigOf(g))}
            onDeleteNode={deleteNode}
            onDeleteEdge={deleteEdge}
            kbs={kbs}
            agents={agents}
            mxInstalls={mxInstalls}
            mxActions={mxActions}
          />
        ) : (
          <aside className="w-72 shrink-0 rounded-md border border-border bg-raised/60 p-3 text-[11px] text-faint">
            Selecciona un nodo para configurarlo.
          </aside>
        )}
      </div>

      <WorkflowRunInspector
        run={run}
        plannedEffects={(runResult?.planned_effects as { node_id: string; node_type: string; planned: Record<string, unknown> }[] | undefined)}
        onClose={() => setRun(null)}
      />
    </div>
  );
}