import { ArrowLeft, Code, FloppyDisk, Lightning, MagicWand, SlidersHorizontal, X } from "@phosphor-icons/react";
import { useCallback, useEffect, useMemo, useState } from "react";
import { useLocation, useNavigate, useParams, useSearchParams } from "react-router-dom";
import { api } from "../api";
import { useAuth } from "../auth";
import { Breadcrumb } from "../components/Breadcrumb";
import { ErrorInline, PageHeader, SkeletonBlock, Spinner, SuccessInline } from "../components/ui";
import { WorkflowCanvasEditor } from "../components/WorkflowCanvasEditor";
import type { RunOverlay } from "../components/WorkflowCanvas";
import type { RunDetail } from "../components/WorkflowRunInspector";
import { WorkflowApiPanel } from "../components/workflowStudio/WorkflowApiPanel";
import { WorkflowHealthBar } from "../components/workflowStudio/WorkflowHealthBar";
import { WorkflowPatchPanel } from "../components/workflowStudio/WorkflowPatchPanel";
import { WorkflowTestPanel } from "../components/workflowStudio/WorkflowTestPanel";
import { WorkflowVersionsPanel } from "../components/workflowStudio/WorkflowVersionsPanel";
import {
  STATUS_BADGE,
  STUDIO_DRAWER_LABELS,
  isStudioDrawer,
  type AgentOption,
  type KbOption,
  type StudioDrawer,
  type WorkflowDetail,
} from "../components/workflowStudio/types";
import type { ParameterLevel } from "../lib/businessSchema";
import type { WorkflowGraph } from "../lib/workflowGraph";
import {
  effectNodes,
  emptyGraph,
  graphIssues,
  nodeMeta,
  prepareGraphForSave,
  triggerConfigOf,
  triggerTypeOf,
} from "../lib/workflowGraph";

type StudioState = { hookSecret?: string };

/** Grafo inicial de un workflow nuevo: trigger webhook conectado a un fin. */
function starterGraph(): WorkflowGraph {
  const g = emptyGraph("webhook");
  const trigger = g.nodes[0];
  g.nodes.push({
    id: "end",
    type: "end",
    version: 1,
    label: "Fin",
    position: { x: 340, y: 90 },
    config: {},
    input_ports: [{ name: "in", type: "json" }],
    output_ports: [],
    retry_policy: { max_attempts: 1 },
    timeout_ms: 60_000,
    error_policy: "fail",
    metadata: { automatic: true },
  });
  g.edges.push({ id: "e1", from_node: trigger.id, from_port: "out", to_node: "end", to_port: "in" });
  return g;
}

export default function WorkflowStudioPage() {
  const { id } = useParams<{ id: string }>();
  const isNew = !id || id === "new";
  const navigate = useNavigate();
  const location = useLocation();
  const [searchParams, setSearchParams] = useSearchParams();
  const { session } = useAuth();

  const panel = searchParams.get("panel");
  const drawer: StudioDrawer | null = isStudioDrawer(panel) ? panel : null;

  const [detail, setDetail] = useState<WorkflowDetail | null>(null);
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [graph, setGraph] = useState<WorkflowGraph | null>(null);
  const [kbs, setKbs] = useState<KbOption[]>([]);
  const [agents, setAgents] = useState<AgentOption[]>([]);
  const [loading, setLoading] = useState(!isNew);
  const [saving, setSaving] = useState(false);
  const [statusBusy, setStatusBusy] = useState(false);
  const [error, setError] = useState("");
  const [msg, setMsg] = useState("");
  const [secret, setSecret] = useState((location.state as StudioState | null)?.hookSecret || "");
  const [savedSignature, setSavedSignature] = useState("");
  const [selectedNode, setSelectedNode] = useState<string | null>(null);
  const [configLevel, setConfigLevel] = useState<ParameterLevel>("simple");
  const [run, setRun] = useState<RunDetail | null>(null);
  const [dockOpen, setDockOpen] = useState(panel === "test");
  const [patchOpen, setPatchOpen] = useState(false);
  const [pinnedNodes, setPinnedNodes] = useState<string[]>([]);
  const [partialBusy, setPartialBusy] = useState("");

  const status = detail?.status ?? "draft";

  const signature = useMemo(
    () => JSON.stringify({ name, description, graph: graph ? prepareGraphForSave(graph) : null }),
    [name, description, graph],
  );
  const dirty = !isNew && savedSignature !== "" && signature !== savedSignature;

  const issues = useMemo(() => graphIssues(graph), [graph]);
  const effectLabels = useMemo(
    () => (graph ? effectNodes(graph).map((n) => n.label || nodeMeta(n.type).label) : []),
    [graph],
  );

  /** Estado de cada nodo en el último run: pinta el lienzo. */
  const overlay: RunOverlay = useMemo(() => {
    const out: RunOverlay = {};
    for (const s of run?.steps ?? []) {
      if (!s.node_id) continue;
      const text = typeof (s.output ?? {}).text === "string" ? String((s.output ?? {}).text) : null;
      out[s.node_id] = {
        status: s.status,
        duration_ms: s.duration_ms,
        error: s.error,
        simulated: s.status === "simulated",
        text,
      };
    }
    return out;
  }, [run]);

  useEffect(() => {
    if (!dirty) return;
    function onBeforeUnload(event: BeforeUnloadEvent) {
      event.preventDefault();
      event.returnValue = "";
    }
    window.addEventListener("beforeunload", onBeforeUnload);
    return () => window.removeEventListener("beforeunload", onBeforeUnload);
  }, [dirty]);

  useEffect(() => {
    if (!session) return;
    void Promise.all([
      api<{ knowledge_bases: KbOption[] }>("/api/v1/knowledge-bases", {
        token: session.token,
        organizationId: session.organizationId,
      }).catch(() => ({ knowledge_bases: [] as KbOption[] })),
      api<{ agents: AgentOption[] }>("/api/v1/agents", {
        token: session.token,
        organizationId: session.organizationId,
      }).catch(() => ({ agents: [] as AgentOption[] })),
    ]).then(([kb, ag]) => {
      setKbs(kb.knowledge_bases || []);
      setAgents(ag.agents || []);
    });
  }, [session]);

  const applyDetail = useCallback((d: WorkflowDetail) => {
    setDetail(d);
    setName(d.name);
    setDescription(d.description || "");
    const storedLevel = d.editor_state?.config_level;
    setConfigLevel(storedLevel === "guided" || storedLevel === "advanced" ? storedLevel : "simple");
    const g = d.graph ?? starterGraph();
    setGraph(g);
    setSavedSignature(
      JSON.stringify({
        name: d.name,
        description: d.description || "",
        graph: prepareGraphForSave(g),
      }),
    );
  }, []);

  // `silent` evita el skeleton al refrescar tras guardar: si desmontamos el
  // estudio se pierde lo que el usuario tenía escrito en el dock.
  const load = useCallback(async (silent = false) => {
    if (!session || isNew || !id) return;
    if (!silent) setLoading(true);
    setError("");
    try {
      const d = await api<WorkflowDetail>(`/api/v1/workflows/${id}`, {
        token: session.token,
        organizationId: session.organizationId,
      });
      applyDetail(d);
      try {
        const pinned = await api<{ nodes: { node_id: string }[] }>(
          `/api/v1/workflows/${id}/pinned-data`,
          { token: session.token, organizationId: session.organizationId },
        );
        setPinnedNodes((pinned.nodes || []).map((entry) => entry.node_id));
      } catch {
        setPinnedNodes([]);
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : "Error");
    } finally {
      setLoading(false);
    }
  }, [session, id, isNew, applyDetail]);

  useEffect(() => {
    void load();
  }, [load]);

  // El estudio vive a pantalla completa: un banner fijo le roba alto al lienzo.
  useEffect(() => {
    if (!msg) return;
    const t = window.setTimeout(() => setMsg(""), 2500);
    return () => window.clearTimeout(t);
  }, [msg]);

  function openDrawer(next: StudioDrawer | null) {
    const params = new URLSearchParams(searchParams);
    if (next) params.set("panel", next);
    else params.delete("panel");
    setSearchParams(params, { replace: true });
  }

  async function create() {
    if (!session || !name.trim()) return;
    setSaving(true);
    setError("");
    try {
      const out = await api<{ workflow_id: string; hook_secret?: string }>("/api/v1/workflows", {
        method: "POST",
        token: session.token,
        organizationId: session.organizationId,
        body: JSON.stringify({
          name: name.trim(),
          description: description.trim() || null,
          trigger_type: "webhook",
          trigger_config: {},
          steps: [],
          editor_state: { mode: "canvas", config_level: configLevel },
          graph: starterGraph(),
          workflow_version: 2,
        }),
      });
      navigate(`/workflows/${out.workflow_id}`, {
        replace: true,
        state: { hookSecret: out.hook_secret } satisfies StudioState,
      });
    } catch (e) {
      setError(e instanceof Error ? e.message : "Error");
    } finally {
      setSaving(false);
    }
  }

  /** Devuelve si el grafo quedó persistido: Probar lo usa para no correr una versión vieja. */
  async function save(): Promise<boolean> {
    if (!session || !id || isNew || !name.trim() || !graph) return false;
    setSaving(true);
    setError("");
    setMsg("");
    try {
      const g = prepareGraphForSave(graph);
      const ttype = triggerTypeOf(g);
      const tcfg = triggerConfigOf(g);
      await api(`/api/v1/workflows/${id}`, {
        method: "PATCH",
        token: session.token,
        organizationId: session.organizationId,
        body: JSON.stringify({
          name: name.trim(),
          description: description.trim() || null,
          graph: g,
          workflow_version: 2,
          trigger_type: ttype,
          trigger_config: tcfg,
          editor_state: { ...(detail?.editor_state ?? {}), mode: "canvas", config_level: configLevel },
        }),
      });
      // Trigger de evento: la suscripción vive en su propia tabla.
      if (ttype === "event" && tcfg.event_type) {
        await api("/api/v1/workflows/triggers", {
          method: "POST",
          token: session.token,
          organizationId: session.organizationId,
          body: JSON.stringify({
            workflow_id: id,
            event_type: String(tcfg.event_type),
            filters: (tcfg.filters as Record<string, unknown>) ?? {},
          }),
        }).catch(() => undefined);
      }
      setMsg("Guardado ✓");
      await load(true);
      return true;
    } catch (e) {
      setError(e instanceof Error ? e.message : "Error");
      return false;
    } finally {
      setSaving(false);
    }
  }

  async function toggleStatus(activate: boolean) {
    if (!session || !id || isNew) return;
    setStatusBusy(true);
    setError("");
    setMsg("");
    try {
      await api(`/api/v1/workflows/${id}/${activate ? "activate" : "pause"}`, {
        method: "POST",
        token: session.token,
        organizationId: session.organizationId,
      });
      setMsg(activate ? "Workflow activo." : "Workflow pausado.");
      setDetail((prev) => (prev ? { ...prev, status: activate ? "active" : "paused" } : prev));
    } catch (e) {
      setError(e instanceof Error ? e.message : "Error");
    } finally {
      setStatusBusy(false);
    }
  }

  async function pinData(nodeId: string, output: Record<string, unknown>) {
    if (!session || !id) return;
    setError("");
    try {
      await api(`/api/v1/workflows/${id}/pinned-data/${encodeURIComponent(nodeId)}`, {
        method: "PUT",
        token: session.token,
        organizationId: session.organizationId,
        body: JSON.stringify({ output }),
      });
      setPinnedNodes((prev) => [...new Set([...prev, nodeId])]);
      setMsg("Datos fijados solo para pruebas.");
    } catch (e) {
      setError(e instanceof Error ? e.message : "Error");
    }
  }

  async function unpinData(nodeId: string) {
    if (!session || !id) return;
    setError("");
    try {
      await api(`/api/v1/workflows/${id}/pinned-data/${encodeURIComponent(nodeId)}`, {
        method: "DELETE",
        token: session.token,
        organizationId: session.organizationId,
      });
      setPinnedNodes((prev) => prev.filter((entry) => entry !== nodeId));
    } catch (e) {
      setError(e instanceof Error ? e.message : "Error");
    }
  }

  async function partialRun(nodeId: string, mode: "node" | "until_node" | "from_node") {
    if (!session || !id) return;
    setPartialBusy(nodeId);
    setError("");
    try {
      const out = await api<{ run_id?: string; status?: string; error?: string }>(
        `/api/v1/workflows/${id}/run`,
        {
          method: "POST",
          token: session.token,
          organizationId: session.organizationId,
          body: JSON.stringify({ payload: {}, simulate: true, run_mode: mode, target_node_id: nodeId }),
        },
      );
      if (out.run_id) {
        const detail = await api<RunDetail>(`/api/v1/workflows/runs/${out.run_id}`, {
          token: session.token,
          organizationId: session.organizationId,
        });
        setRun(detail);
        const failed = (detail.steps ?? []).find((step) => step.status === "failed");
        if (failed) setError(failed.error || "La ejecución parcial falló.");
      }
      await load(true);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Error");
    } finally {
      setPartialBusy("");
    }
  }

  function back() {
    if (dirty && !window.confirm("Hay cambios sin guardar. ¿Salir sin guardar?")) return;
    navigate("/workflows");
  }

  function selectFromDock(nodeId: string) {
    setSelectedNode(nodeId);
    setDockOpen(false);
  }

  if (loading) {
    return (
      <div className="panel p-5">
        <SkeletonBlock rows={6} />
      </div>
    );
  }

  if (isNew) {
    return (
      <div>
        <Breadcrumb items={[{ label: "Workflows", to: "/workflows" }, { label: "Nuevo workflow" }]} />
        <PageHeader
          title="Nuevo workflow"
          subtitle="Ponle nombre: el lienzo se abre con el trigger listo para conectar nodos."
        />
        <ErrorInline message={error} />
        <div className="panel max-w-xl space-y-4 p-5">
          <label className="block text-sm text-muted">
            Nombre
            <input
              className="mt-1 w-full rounded-md border border-border bg-soft px-3 py-2 text-sm"
              placeholder="Alerta de stock bajo"
              value={name}
              onChange={(e) => setName(e.target.value)}
              data-testid="wf-new-name"
            />
          </label>
          <label className="block text-sm text-muted">
            Qué hace (opcional)
            <input
              className="mt-1 w-full rounded-md border border-border bg-soft px-3 py-2 text-sm"
              placeholder="Avisa al equipo cuando queden menos de 5 unidades"
              value={description}
              onChange={(e) => setDescription(e.target.value)}
            />
          </label>
          <div className="flex flex-wrap gap-2">
            <button
              type="button"
              className="btn btn-primary min-h-11 text-sm"
              disabled={saving || !name.trim()}
              onClick={() => void create()}
              data-testid="wf-create"
            >
              {saving ? <Spinner size={14} /> : <Lightning size={15} aria-hidden />}
              Crear y abrir el lienzo
            </button>
            <button type="button" className="btn btn-ghost min-h-11 text-sm" onClick={back}>
              <ArrowLeft size={16} aria-hidden /> Volver
            </button>
          </div>
        </div>
      </div>
    );
  }

  return (
    // El shell pone la ruta en modo full-bleed (ver `fullBleed` en App.tsx):
    // aquí solo repartimos la altura entre cabecera, lienzo y dock.
    <div className="flex h-[calc(100dvh-5.5rem)] min-h-[34rem] min-w-0 flex-col gap-2 lg:h-[calc(100dvh-1.5rem)]">
      <header className="flex flex-wrap items-center gap-x-3 gap-y-2 border-b border-border pb-3">
        <button
          type="button"
          className="btn btn-ghost min-h-11 shrink-0 px-2"
          onClick={back}
          aria-label="Volver a workflows"
        >
          <ArrowLeft size={16} aria-hidden />
        </button>
        <div className="min-w-[12rem] flex-1">
          <input
            className="w-full rounded-md border border-transparent bg-transparent px-1.5 py-1 text-[17px] font-semibold text-text hover:border-border focus:border-border focus:bg-soft"
            value={name}
            onChange={(e) => setName(e.target.value)}
            aria-label="Nombre del workflow"
            data-testid="wf-name"
          />
          <input
            className="w-full rounded-md border border-transparent bg-transparent px-1.5 py-0.5 text-xs text-muted hover:border-border focus:border-border focus:bg-soft"
            value={description}
            placeholder="Añade una descripción corta"
            onChange={(e) => setDescription(e.target.value)}
            aria-label="Descripción del workflow"
          />
        </div>
        <div className="flex flex-wrap items-center gap-2">
          {dirty && <span className="badge badge-pending">Cambios sin guardar</span>}
          <span className={`badge ${STATUS_BADGE[status] ?? "badge-muted"}`}>{status}</span>
          <label className="flex min-h-11 items-center gap-2 text-sm text-muted">
            <input
              type="checkbox"
              checked={status === "active"}
              disabled={statusBusy}
              onChange={(e) => void toggleStatus(e.target.checked)}
              data-testid="wf-active-toggle"
            />
            Activo
          </label>
          <button
            type="button"
            className="btn btn-secondary min-h-11 px-2.5 text-xs"
            onClick={() => openDrawer("api")}
            data-testid="wf-open-api"
          >
            <Code size={15} aria-hidden /> API
          </button>
          <button
            type="button"
            className="btn btn-secondary min-h-11 px-2.5 text-xs"
            onClick={() => openDrawer("advanced")}
            data-testid="wf-open-advanced"
          >
            <SlidersHorizontal size={15} aria-hidden /> Avanzado
          </button>
          <button
            type="button"
            className="btn btn-secondary min-h-11 px-2.5 text-xs"
            onClick={() => setPatchOpen(true)}
            data-testid="wf-open-patch"
          >
            <MagicWand size={15} aria-hidden /> Editar con IA
          </button>
          <button
            type="button"
            className="btn btn-ghost min-h-11 px-2.5 text-xs lg:hidden"
            onClick={() => setDockOpen(true)}
            data-testid="wf-open-dock"
          >
            Probar
          </button>
          <button
            type="button"
            className="btn btn-primary min-h-11 px-3 text-xs"
            disabled={saving || !name.trim()}
            onClick={() => void save()}
            data-testid="wf-save"
          >
            {saving ? <Spinner size={14} /> : <FloppyDisk size={15} aria-hidden />}
            Guardar
          </button>
        </div>
      </header>

      {(error || msg) && (
        <div className="shrink-0">
          <ErrorInline message={error} />
          <SuccessInline message={msg} />
        </div>
      )}

      {id && <WorkflowHealthBar workflowId={id} refreshKey={detail?.updated_at ?? ""} />}

      <div className="flex min-h-0 flex-1 gap-3">
        <div className="min-w-0 flex-1">
          <WorkflowCanvasEditor
            heightClass="h-full"
            workflowId={id ?? null}
            graph={graph}
            onChangeGraph={(g) => setGraph(structuredClone(g))}
            kbs={kbs}
            agents={agents}
            overlay={overlay}
            selectedNodeId={selectedNode}
            onSelectNode={setSelectedNode}
            configLevel={configLevel}
            onConfigLevelChange={setConfigLevel}
            run={run}
            pinnedNodes={pinnedNodes}
            onPinData={(nodeId, output) => void pinData(nodeId, output)}
            onUnpinData={(nodeId) => void unpinData(nodeId)}
            onRunPartial={(nodeId, mode) => void partialRun(nodeId, mode)}
            partialBusy={partialBusy}
          />
        </div>
        {id && (
          <aside className="hidden w-80 shrink-0 lg:flex xl:w-[22rem]">
            <WorkflowTestPanel
              workflowId={id}
              status={status}
              effectLabels={effectLabels}
              issues={issues}
              dirty={dirty}
              onRun={setRun}
              onSelectNode={setSelectedNode}
              onRan={() => void load(true)}
              onSaveBeforeRun={save}
              graph={graph}
            />
          </aside>
        )}
      </div>

      {/* Mobile: el dock de prueba es una hoja inferior. */}
      {dockOpen && id && (
        <div className="fixed inset-0 z-40 flex items-end bg-black/40 lg:hidden" onClick={() => setDockOpen(false)}>
          <div
            className="max-h-[85dvh] w-full"
            onClick={(e) => e.stopPropagation()}
            data-testid="wf-dock-sheet"
          >
            <div className="flex h-[80dvh] flex-col">
              <WorkflowTestPanel
                workflowId={id}
                status={status}
                effectLabels={effectLabels}
                issues={issues}
                dirty={dirty}
                onRun={setRun}
                onSelectNode={selectFromDock}
                onRan={() => void load(true)}
                onSaveBeforeRun={save}
              graph={graph}
              />
            </div>
          </div>
        </div>
      )}

      {drawer && id && (
        <div className="fixed inset-0 z-50 flex justify-end bg-black/40" onClick={() => openDrawer(null)}>
          <div
            className="flex h-full w-full max-w-xl flex-col border-l border-border bg-bg"
            onClick={(e) => e.stopPropagation()}
            role="dialog"
            aria-label={STUDIO_DRAWER_LABELS[drawer]}
            data-testid={`wf-drawer-${drawer}`}
          >
            <div className="flex items-center gap-2 border-b border-border px-4 py-3">
              <h2 className="flex-1 text-sm font-semibold text-text">{STUDIO_DRAWER_LABELS[drawer]}</h2>
              <button
                type="button"
                className="btn btn-ghost min-h-9 px-2"
                aria-label="Cerrar"
                onClick={() => openDrawer(null)}
              >
                <X size={16} aria-hidden />
              </button>
            </div>
            <div className="min-h-0 flex-1 overflow-y-auto p-4">
              {drawer === "api" ? (
                <WorkflowApiPanel
                  workflowId={id}
                  status={status}
                  triggerType={detail?.trigger_type ?? "webhook"}
                  hookPath={detail?.hook_url || `/api/v1/public/workflows/${id}/hook`}
                  hasHookSecret={Boolean(detail?.has_hook_secret) || Boolean(secret)}
                  secret={secret}
                  onSecret={setSecret}
                />
              ) : (
                <WorkflowVersionsPanel workflowId={id} status={status} onChanged={() => void load(true)} />
              )}
            </div>
          </div>
        </div>
      )}

      {patchOpen && id && (
        <div className="fixed inset-0 z-50 flex justify-end bg-black/40" onClick={() => setPatchOpen(false)}>
          <div
            className="flex h-full w-full max-w-lg flex-col border-l border-border bg-bg"
            onClick={(e) => e.stopPropagation()}
            role="dialog"
            aria-label="Editar con IA"
            data-testid="wf-patch-drawer"
          >
            <div className="flex items-center gap-2 border-b border-border px-4 py-3">
              <h2 className="flex-1 text-sm font-semibold text-text">Editar con IA</h2>
              <button
                type="button"
                className="btn btn-ghost min-h-9 px-2"
                aria-label="Cerrar"
                onClick={() => setPatchOpen(false)}
              >
                <X size={16} aria-hidden />
              </button>
            </div>
            <div className="min-h-0 flex-1 overflow-y-auto p-4">
              <WorkflowPatchPanel
                workflowId={id}
                onClose={() => setPatchOpen(false)}
                onApplied={() => {
                  setPatchOpen(false);
                  void load(true);
                }}
              />
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
