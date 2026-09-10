import { FloppyDisk, Play, Flask, ChartLineUp, WarningOctagon, X, Plus } from "@phosphor-icons/react";
import { useCallback, useEffect, useMemo, useState } from "react";
import { api } from "../api";
import { useAuth } from "../auth";
import type { MarketRec, ShopInstall } from "../lib/marketplaceCanvas";
import type { WorkflowGraph } from "../lib/workflowGraph";
import { makeNode, newEdgeId, prepareGraphForSave, triggerConfigOf, triggerTypeOf } from "../lib/workflowGraph";
import { NodeConfigPanel } from "./NodeConfigPanel";
import { NodeLibrary, type MarketplaceContext, type MxRecommendation } from "./NodeLibrary";
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
  const [mkt, setMkt] = useState<MarketplaceContext | null>(null);
  const [shop, setShop] = useState<ShopInstall | null>(null);
  const [shopBusy, setShopBusy] = useState(false);
  const [shopPurpose, setShopPurpose] = useState("");
  const [cost, setCost] = useState<{ per_run: number; monthly: number; calls_per_run: number; bulk_warning: boolean; currency: string } | null>(null);
  const [bulkConfirmed, setBulkConfirmed] = useState(false);
  const [emptyDismissed, setEmptyDismissed] = useState(false);

  useEffect(() => {
    if (!session) return;
    api<{ installs: { id: string; integration: { slug: string; name: string } }[] }>(
      "/api/v1/integrations/installs",
      { token: session.token, organizationId: session.organizationId }
    )
      .then((d) => setMxInstalls(d.installs || []))
      .catch(() => undefined);

    api<MarketplaceContext>("/api/v1/workflows/marketplace/context", {
      token: session.token,
      organizationId: session.organizationId,
    })
      .then((d) => setMkt(d))
      .catch(() => undefined);
  }, [session, workflowId]);

  // Recomendaciones y costo según el grafo actual (debounce ligero).
  useEffect(() => {
    if (!session || !graph || graph.nodes.length <= 1) {
      setCost(null);
      return;
    }
    const id = window.setTimeout(() => {
      const g = prepareGraphForSave(graph);
      void api<{ recommendations: MxRecommendation[] }>("/api/v1/workflows/marketplace/recommend", {
        method: "POST",
        token: session.token,
        organizationId: session.organizationId,
        body: JSON.stringify({ graph: g }),
      })
        .then((d) => setMkt((prev) => (prev ? { ...prev, recommendations: d.recommendations || [] } : prev)))
        .catch(() => undefined);
      void api<{ per_run: number; monthly: number; calls_per_run: number; bulk_warning: boolean; currency: string }>(
        "/api/v1/workflows/cost-estimate",
        {
          method: "POST",
          token: session.token,
          organizationId: session.organizationId,
          body: JSON.stringify({ graph: g, trigger_config: triggerConfigOf(g) }),
        }
      )
        .then(setCost)
        .catch(() => undefined);
    }, 600);
    return () => window.clearTimeout(id);
     
  }, [session, graph]);

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

  function addNodeWithConfig(nodeType: string, config: Record<string, unknown>) {
    if (!graph || !workflowId) return;
    const count = graph.nodes.length;
    const n = makeNode(nodeType, { x: 40 + (count % 5) * 40, y: 60 + (count % 4) * 40 });
    n.config = { ...n.config, ...config };
    const copy: WorkflowGraph = {
      ...graph,
      nodes: [...graph.nodes.map((x) => ({ ...x, config: { ...x.config } })), n],
      entrypoints: graph.entrypoints.length ? graph.entrypoints : [n.id],
    };
    onChangeGraph(copy, triggerTypeOf(copy), triggerConfigOf(copy));
    setSelectedNode(n.id);
  }

  function addMarketplaceAction(installId: string, action: { action_id: string; display_name: string; renderer?: string | null }) {
    addNodeWithConfig("marketplace_action", {
      install_id: installId,
      action_id: action.action_id,
      renderer: action.renderer ?? null,
      inputs: {},
    });
  }

  async function addRecommendation(rec: MxRecommendation) {
    // Instala si falta; luego añade el nodo con la acción recomendada.
    if (!session) return;
    const available = mkt?.available.find((a) => a.slug === rec.integration_slug);
    const want = available?.actions.find((a) => a.action_id === rec.action_id);
    if (want && available) {
      const installed = mkt?.installed.find((i) => i.integration.slug === rec.integration_slug);
      if (!installed) {
        setShop({
          slug: available.slug,
          name: available.name,
          description: available.description ?? "",
          requires_credentials: Boolean(available.requires_credentials),
          requires_purpose: Boolean(available.requires_purpose),
          actions: [want],
        });
        return;
      }
      addMarketplaceAction(installed.install_id, want);
      return;
    }
    addNodeWithConfig("marketplace_action", { install_id: "", action_id: rec.action_id, inputs: {} });
  }

  async function installFromDrawer(slug: string) {
    if (!session) return;
    setShopBusy(true);
    setError("");
    try {
      const r = await api<MarketRec>(`/api/v1/workflows/marketplace/install`, {
        method: "POST",
        token: session.token,
        organizationId: session.organizationId,
        body: JSON.stringify({ integration_slug: slug, purpose: shopPurpose.trim() || null }),
      });
      const fresh = await api<MarketplaceContext>("/api/v1/workflows/marketplace/context", {
        token: session.token,
        organizationId: session.organizationId,
      });
      setMkt(fresh);
      setError(`Integración instalada ✓ — ${r.integration.name} ya está en el canvas.`);
      setShop(null);
      setShopPurpose("");
    } catch (e) {
      setError(e instanceof Error ? e.message : "Error");
    } finally {
      setShopBusy(false);
    }
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
        body: JSON.stringify({
          graph: g,
          workflow_version: 2,
          trigger_type: ttype,
          trigger_config: tcfg,
        }),
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
    if (cost?.bulk_warning && !bulkConfirmed) {
      const ok = window.confirm(
        `⚠️ Este flujo haría ~${cost.calls_per_run} llamadas externas pagadas por run. ` +
          `Costo máximo estimado: S/ ${cost.per_run.toFixed(2)} por run. ¿Continuar?`
      );
      if (!ok) return;
      setBulkConfirmed(true);
    }
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

  const isEmptyCanvas = !!local && local.nodes.length === 1 && local.edges.length === 0 && !emptyDismissed;

  function addSuggestion(kind: "verify" | "sales" | "invoice" | "inventory") {
    if (!graph || !workflowId) return;
    const nodes = [makeNode(kind === "verify" ? "trigger_event" : "trigger_schedule", { x: 40, y: 60 })];
    const edges: WorkflowGraph["edges"] = [];
    let prev = nodes[0].id;
    if (kind === "verify") {
      nodes[0].config = { event_type: "customer.created", filters: {} };
      const first = mxInstalls[0];
      const actions = first ? mxActions[first.id] : [];
      const act = actions[0];
      if (first && act) {
        nodes.push(makeNode("marketplace_action", { x: 340, y: 140 }));
        nodes[nodes.length - 1].config = { install_id: first.id, action_id: act.action_id, inputs: { ruc: "{{trigger.ruc}}" } };
      } else {
        nodes.push(makeNode("marketplace_action", { x: 340, y: 140 }));
      }
      const nid = nodes[nodes.length - 1].id;
      edges.push({ id: newEdgeId(), from_node: prev, from_port: "out", to_node: nid, to_port: "in" });
      prev = nid;
      const cond = makeNode("condition", { x: 600, y: 200 });
      cond.config = { field: `{{nodes.${nid}.output.status}}`, operator: "!=", value: "ACTIVO" };
      nodes.push(cond);
      edges.push({ id: newEdgeId(), from_node: prev, from_port: "out", to_node: cond.id, to_port: "in" });
      prev = cond.id;
    } else {
      const q = makeNode("query_business_data", { x: 340, y: 140 });
      q.config = { ask: kind === "sales" ? "Ventas de ayer" : kind === "invoice" ? "Facturas por verificar" : "Stock bajo" };
      nodes.push(q);
      edges.push({ id: newEdgeId(), from_node: prev, from_port: "out", to_node: q.id, to_port: "in" });
      prev = q.id;
    }
    const notify = makeNode("notify", { x: 860, y: 240 });
    notify.config = {
      channel: "in_app",
      title: kind === "verify" ? "Cliente no activo" : "Reporte",
      message: `{{nodes.${prev}.output}}`,
    };
    nodes.push(notify);
    edges.push({ id: newEdgeId(), from_node: prev, from_port: "out", to_node: notify.id, to_port: "in" });

    const existing = graph.nodes.filter((n) => n.type.startsWith("trigger_"));
    const copy: WorkflowGraph = {
      ...graph,
      nodes: [...existing.map((x) => ({ ...x, config: { ...x.config } })), ...nodes],
      edges: [...graph.edges, ...edges],
      entrypoints: existing.map((x) => x.id),
    };
    onChangeGraph(copy, triggerTypeOf(copy), triggerConfigOf(copy));
  }

  const selectedNodeObj = local?.nodes.find((n) => n.id === selectedNode) ?? null;
  const selectedEdgeObj = local?.edges.find((e) => e.id === selectedEdge) ?? null;

  return (
    <div className="space-y-3" data-testid="workflow-canvas-editor">
      {error && <ErrorInline>{error}</ErrorInline>}

      {isEmptyCanvas && (
        <div className="rounded-md border border-accent/30 bg-accent/5 p-3" data-testid="wf-empty-hint">
          <p className="text-sm font-medium text-text">¿Qué quieres automatizar?</p>
          <p className="mt-0.5 text-xs text-muted">Empieza con una plantilla en el canvas; la editas sin salir.</p>
          <div className="mt-2 flex flex-wrap gap-2">
            {(
              [
                ["verify", "Verificar clientes nuevos"],
                ["sales", "Daily Sales Report"],
                ["invoice", "Invoice Verification"],
                ["inventory", "Inventory Alerts"],
              ] as const
            ).map(([kind, label]) => (
              <button
                key={kind}
                type="button"
                className="btn btn-ghost min-h-8 gap-1 px-2 text-[11px]"
                data-testid={`wf-suggest-${kind}`}
                onClick={() => addSuggestion(kind)}
              >
                + {label}
              </button>
            ))}
            <button
              type="button"
              className="btn btn-ghost min-h-8 px-2 text-[11px] text-faint"
              data-testid="wf-suggest-blank"
              onClick={() => setEmptyDismissed(true)}
            >
              Start Blank
            </button>
          </div>
        </div>
      )}

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
        {cost && cost.calls_per_run > 0 && (
          <span
            className="inline-flex items-center gap-1 rounded-md border border-border bg-soft px-2 py-1 text-[10px] text-muted"
            data-testid="wf-cost"
            title={`${cost.calls_per_run} llamadas por run`}
          >
            <ChartLineUp size={12} aria-hidden />
            ~ S/ {cost.per_run.toFixed(2)} / run · S/ {cost.monthly.toFixed(2)} / mes
          </span>
        )}
        {cost?.bulk_warning && !bulkConfirmed && (
          <button
            type="button"
            className="inline-flex items-center gap-1 rounded-md border border-danger/40 bg-danger/10 px-2 py-1 text-[10px] text-danger"
            data-testid="wf-bulk-warning"
            onClick={() =>
              setError(
                `Bulk: ~${cost.calls_per_run} llamadas externas pagadas; max ~S/ ${cost.per_run.toFixed(2)} por run. Confirma al ejecutar.`
              )
            }
          >
            <WarningOctagon size={12} aria-hidden />
            Bulk: {cost.calls_per_run} llamadas
          </button>
        )}
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
          marketplace={mkt}
          onAddMarketplaceAction={addMarketplaceAction}
          onAddRecommendation={(r) => void addRecommendation(r)}
          onInstall={(slug) => {
            const a = mkt?.available.find((x) => x.slug === slug);
            if (a) {
              setShop({ slug: a.slug, name: a.name, description: a.description ?? "", requires_credentials: a.requires_credentials, requires_purpose: a.requires_purpose, actions: a.actions });
            }
          }}
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

      {shop && (
        <div className="fixed inset-0 z-40 flex items-end justify-center bg-black/40 p-0 sm:items-center sm:p-6" data-testid="wf-mkt-drawer">
          <div className="max-h-[90dvh] w-full max-w-md overflow-y-auto rounded-t-lg border border-border bg-surface p-5 sm:rounded-lg">
            <div className="flex items-start justify-between gap-3">
              <div className="flex items-center gap-2">
                <MarketBadge slug={shop.slug} />
                <div>
                  <p className="text-sm font-semibold text-text">{shop.name}</p>
                  <p className="text-[11px] text-faint">{shop.slug}</p>
                </div>
              </div>
              <button type="button" className="btn btn-ghost min-h-8 min-w-8 rounded-md" aria-label="Cerrar instalación" onClick={() => setShop(null)}>
                <X size={15} aria-hidden />
              </button>
            </div>
            {shop.description && <p className="mt-2 text-xs text-muted">{shop.description}</p>}

            <dl className="mt-4 space-y-2 text-xs">
              <div className="flex justify-between gap-3">
                <dt className="text-faint">Provider</dt>
                <dd className="text-text capitalize">{shop.requires_credentials ? "Requiere credenciales" : "Zent managed"}</dd>
              </div>
              <div className="flex justify-between gap-3">
                <dt className="text-faint">Pricing</dt>
                <dd className="text-right text-text">{shop.actions.map((a) => `${a.display_name}${a.cost.price > 0 ? ` S/ ${a.cost.price}` : " (gratis)"}`).join(" · ")}</dd>
              </div>
              <div className="flex justify-between gap-3">
                <dt className="text-faint">Data</dt>
                <dd className="text-right text-text">{shop.requires_credentials ? "Secrets en SecretStore" : "Sin datos sensibles"}</dd>
              </div>
              <div className="flex justify-between gap-3">
                <dt className="text-faint">Setup</dt>
                <dd className="text-text">{shop.requires_credentials ? "Credenciales en SecretStore tras instalar" : "Sin setup"}</dd>
              </div>
            </dl>

            <label className="mt-3 block text-[11px] text-muted">
              {shop.requires_purpose ? (
                <span className="font-medium text-text">
                  Propósito de uso <span className="text-danger">*</span> — maneja datos personales
                </span>
              ) : (
                "Propósito de uso (opcional)"
              )}
              <input
                className="input mt-1 w-full"
                placeholder="Verificación de clientes…"
                value={shopPurpose}
                onChange={(e) => setShopPurpose(e.target.value)}
                data-testid="wf-mkt-purpose"
              />
            </label>
            {shop.requires_purpose && !shopPurpose.trim() && (
              <p className="mt-1 text-[10px] text-danger" data-testid="wf-mkt-purpose-hint">
                Indica el propósito para habilitar la instalación.
              </p>
            )}

            <button
              type="button"
              className="btn btn-primary mt-5 w-full gap-1.5 text-sm"
              disabled={shopBusy || (Boolean(shop.requires_purpose) && !shopPurpose.trim())}
              data-testid="wf-mkt-install-confirm"
              onClick={() => void installFromDrawer(shop.slug)}
            >
              <Plus size={15} aria-hidden />
              {shopBusy ? "Instalando…" : "Instalar"}
            </button>
            <p className="mt-2 text-center text-[10px] text-faint">No abandonas el workflow: la capacidad queda disponible al instante.</p>
          </div>
        </div>
      )}
    </div>
  );
}

function MarketBadge({ slug }: { slug: string }) {
  const letter = slug.slice(0, 1).toUpperCase();
  return (
    <span className="flex h-9 w-9 items-center justify-center rounded-md bg-fuchsia-500/15 text-sm font-semibold text-fuchsia-400" aria-hidden>
      {letter}
    </span>
  );
}