import { ArrowClockwise, ArrowCounterClockwise, ArrowLeft, Brain, ChatCircleDots, Code, FloppyDisk, Lightning, MagicWand, SlidersHorizontal } from "@phosphor-icons/react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useLocation, useNavigate, useParams, useSearchParams } from "react-router-dom";
import { api } from "../api";
import { isApiError } from "../lib/errors";
import { useMediaQuery } from "../lib/useMediaQuery";
import { useAuth } from "../auth";
import { Breadcrumb } from "../components/Breadcrumb";
import {
  Button,
  ButtonLink,
  ConfirmDialog,
  Drawer,
  ErrorInline,
  Field,
  FormActions,
  IconButton,
  InlineFlash,
  Input,
  PageHeader,
  SaveStatus,
  SkeletonBlock,
  StatusBadge,
  Switch,
} from "../components/ui";
import type { SaveState } from "../components/ui";
import { WorkflowCanvasEditor } from "../components/WorkflowCanvasEditor";
import type { RunOverlay } from "../components/WorkflowCanvas";
import type { RunDetail } from "../components/WorkflowRunInspector";
import { AgentMemoryPanel } from "../components/workflowStudio/AgentMemoryPanel";
import { SubflowLibraryPanel } from "../components/workflowStudio/SubflowLibraryPanel";
import { WorkflowApiPanel } from "../components/workflowStudio/WorkflowApiPanel";
import { WorkflowHealthBar } from "../components/workflowStudio/WorkflowHealthBar";
import { SalesFunnelChecklist } from "../components/commerce/SalesFunnelChecklist";
import { SalesFunnelKpis } from "../components/commerce/SalesFunnelKpis";
import { MissionCard, missionFromGraph, type MissionFields } from "../components/workflowStudio/MissionCard";
import { WorkflowPatchPanel } from "../components/workflowStudio/WorkflowPatchPanel";
import { WorkflowTestPanel } from "../components/workflowStudio/WorkflowTestPanel";
import { WorkflowVersionsPanel } from "../components/workflowStudio/WorkflowVersionsPanel";
import {
  STUDIO_DRAWER_LABELS,
  isStudioDrawer,
  type AgentOption,
  type KbOption,
  type StudioDrawer,
  type WorkflowDetail,
} from "../components/workflowStudio/types";
import type { ParameterLevel } from "../lib/businessSchema";
import type { GraphNode, WorkflowGraph } from "../lib/workflowGraph";
import {
  effectNodes,
  emptyGraph,
  graphIssues,
  newGraphNodeId,
  nodeMeta,
  prepareGraphForSave,
  triggerConfigOf,
  triggerTypeOf,
} from "../lib/workflowGraph";

type StudioState = { hookSecret?: string };

/** Grafo inicial de un workflow nuevo: trigger webhook conectado a un fin. */
/** ¿El grafo es el embudo de ventas oficial? (metadata.template de la plantilla). */
function isSalesFunnel(graph: WorkflowGraph | null | undefined): boolean {
  const metadata = (graph?.metadata ?? {}) as Record<string, unknown>;
  return metadata.template === "retail_sales_funnel";
}

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

function mentorGraph(): WorkflowGraph {
  const graph = starterGraph();
  const trigger = graph.nodes[0];
  graph.nodes.splice(1, 0, {
    id: "mentor",
    type: "llm",
    version: 1,
    label: "Acompañar",
    position: { x: 180, y: 90 },
    config: { purpose: "Siguiente ejercicio con el progreso autorizado" },
    input_ports: [{ name: "in", type: "json" }],
    output_ports: [{ name: "out", type: "json" }],
    retry_policy: { max_attempts: 1 },
    timeout_ms: 60_000,
    error_policy: "fail",
    metadata: {},
  });
  graph.edges = [
    { id: "e1", from_node: trigger.id, from_port: "out", to_node: "mentor", to_port: "in" },
    { id: "e2", from_node: "mentor", from_port: "out", to_node: "end", to_port: "in" },
  ];
  graph.metadata = {
    ...graph.metadata,
    mission: {
      role: "Mentor",
      audience: "Persona que aprende",
      goal: "Acompañar el siguiente ejercicio con el progreso autorizado",
      limits: "No inventa evaluación ni diagnóstico",
      capabilities: "Consultar progreso, proponer ejercicio",
      sources: "Conocimiento del curso",
      memory: "Solo con consentimiento",
      actions: "Registrar progreso, pedir aclaración",
      outcomes: "Siguiente ejercicio y avance registrado",
    },
  };
  return graph;
}

function draftKey(workflowId: string): string {
  return `wf-draft-${workflowId}`;
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
  const historyRef = useRef<{ past: WorkflowGraph[]; future: WorkflowGraph[] }>({
    past: [],
    future: [],
  });
  const graphRef = useRef<WorkflowGraph | null>(null);
  const historyStampRef = useRef(0);
  const [historyState, setHistoryState] = useState({ canUndo: false, canRedo: false });
  const [run, setRun] = useState<RunDetail | null>(null);
  const isDesktop = useMediaQuery("(min-width: 1024px)", true);
  // Un solo panel activo: aside en desktop, hoja inferior en móvil. El drawer
  // conserva su contenido montado para no perder el resultado al seleccionar
  // un nodo del lienzo.
  const [dockOpen, setDockOpen] = useState(false);
  const [patchOpen, setPatchOpen] = useState(false);
  const [pinnedNodes, setPinnedNodes] = useState<string[]>([]);
  const [partialBusy, setPartialBusy] = useState("");
  /** Feedback de persistencia: guardado reciente / error de guardado. */
  const [saveFlash, setSaveFlash] = useState<"idle" | "saved">("idle");
  const [saveError, setSaveError] = useState("");
  const [confirmLeave, setConfirmLeave] = useState(false);
  const [conflict, setConflict] = useState(false);
  const [recovery, setRecovery] = useState<{ name: string; description: string; graph: WorkflowGraph } | null>(null);
  const saveRef = useRef<() => Promise<boolean>>(async () => false);

  const status = detail?.status ?? "draft";

  useEffect(() => {
    if (panel === "test" && !isDesktop) setDockOpen(true);
  }, [panel, isDesktop]);

  useEffect(() => {
    if (isDesktop) setDockOpen(false);
  }, [isDesktop]);

  // Un workflow distinto no debe heredar el overlay del anterior.
  useEffect(() => {
    setRun(null);
    setSelectedNode(null);
  }, [id]);

  const signature = useMemo(
    () => JSON.stringify({ name, description, graph: graph ? prepareGraphForSave(graph) : null }),
    [name, description, graph],
  );
  const dirty = !isNew && savedSignature !== "" && signature !== savedSignature;
  const saveIndicator: SaveState = saving
    ? "saving"
    : saveError
      ? "error"
      : saveFlash === "saved"
        ? "saved"
        : dirty
          ? "dirty"
          : "idle";

  useEffect(() => {
    if (saveFlash !== "saved") return;
    const t = window.setTimeout(() => setSaveFlash("idle"), 2600);
    return () => window.clearTimeout(t);
  }, [saveFlash]);

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
      const raw = sessionStorage.getItem(draftKey(id));
      if (raw) {
        try {
          const draft = JSON.parse(raw) as { name?: string; description?: string; graph?: WorkflowGraph };
          const server = JSON.stringify(prepareGraphForSave(d.graph ?? starterGraph()));
          const local = draft.graph ? JSON.stringify(prepareGraphForSave(draft.graph)) : "";
          if (draft.graph && local && local !== server) {
            setRecovery({
              name: draft.name || d.name,
              description: draft.description || "",
              graph: draft.graph,
            });
          } else {
            sessionStorage.removeItem(draftKey(id));
          }
        } catch {
          sessionStorage.removeItem(draftKey(id));
        }
      }
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
          graph: searchParams.get("plantilla") === "mentor" ? mentorGraph() : starterGraph(),
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
    setSaveError("");
    setSaveFlash("idle");
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
      setSaveFlash("saved");
      if (id) sessionStorage.removeItem(draftKey(id));
      setRecovery(null);
      setConflict(false);
      await load(true);
      return true;
    } catch (e) {
      const offline = e instanceof TypeError || (isApiError(e) && (e.status === 0 || e.retryable));
      const clash = isApiError(e) && e.status === 409;
      if (clash) setConflict(true);
      const message = clash
        ? "Otra pestaña guardó este flujo. Tus cambios siguen en esta pestaña."
        : offline
          ? "Sin conexión. Tus cambios siguen en esta pestaña."
          : e instanceof Error
            ? e.message
            : "Error";
      setError(message);
      setSaveError(message);
      return false;
    } finally {
      setSaving(false);
    }
  }

  useEffect(() => {
    saveRef.current = save;
  }, [save]);

  useEffect(() => {
    graphRef.current = graph;
  }, [graph]);

  const commitGraph = useCallback((next: WorkflowGraph) => {
    const previous = graphRef.current ?? graph;
    if (previous) {
      const now = Date.now();
      if (now - historyStampRef.current > 350) {
        historyRef.current.past.push(structuredClone(previous));
        if (historyRef.current.past.length > 40) historyRef.current.past.shift();
        historyRef.current.future = [];
        historyStampRef.current = now;
      }
    }
    graphRef.current = next;
    setGraph(next);
    setHistoryState({
      canUndo: historyRef.current.past.length > 0,
      canRedo: historyRef.current.future.length > 0,
    });
  }, [graph]);

  const undo = useCallback(() => {
    const previous = historyRef.current.past.pop();
    const current = graphRef.current ?? graph;
    if (!previous || !current) return;
    historyRef.current.future.push(structuredClone(current));
    graphRef.current = previous;
    setGraph(previous);
    setHistoryState({
      canUndo: historyRef.current.past.length > 0,
      canRedo: historyRef.current.future.length > 0,
    });
  }, [graph]);

  const redo = useCallback(() => {
    const next = historyRef.current.future.pop();
    const current = graphRef.current ?? graph;
    if (!next || !current) return;
    historyRef.current.past.push(structuredClone(current));
    graphRef.current = next;
    setGraph(next);
    setHistoryState({
      canUndo: historyRef.current.past.length > 0,
      canRedo: historyRef.current.future.length > 0,
    });
  }, [graph]);

  const mentorNamed = useRef(false);
  useEffect(() => {
    if (mentorNamed.current || !isNew || searchParams.get("plantilla") !== "mentor") return;
    mentorNamed.current = true;
    setName((current) => current || "Mentor");
  }, [isNew, searchParams]);

  useEffect(() => {
    if (!id || isNew || !dirty || !graph) return;
    sessionStorage.setItem(draftKey(id), JSON.stringify({ name, description, graph }));
  }, [id, isNew, dirty, name, description, graph]);

  useEffect(() => {
    if (!dirty || conflict || isNew || saving) return;
    const timer = window.setTimeout(() => {
      void saveRef.current();
    }, 1600);
    return () => window.clearTimeout(timer);
  }, [dirty, conflict, isNew, saving, signature]);

  useEffect(() => {
    function onKey(event: KeyboardEvent) {
      const target = event.target as HTMLElement | null;
      const editing =
        target?.tagName === "INPUT" ||
        target?.tagName === "TEXTAREA" ||
        target?.isContentEditable;
      if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "s") {
        event.preventDefault();
        if (!isNew) void saveRef.current();
        return;
      }
      if (editing) return;
      if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "z") {
        event.preventDefault();
        if (event.shiftKey) redo();
        else undo();
      }
      if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "y") {
        event.preventDefault();
        redo();
      }
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [isNew, redo, undo]);

  function updateMission(next: MissionFields) {
    setGraph((current) =>
      current ? { ...current, metadata: { ...current.metadata, mission: next } } : current,
    );
  }

  function applyRecovery() {
    if (!recovery) return;
    setName(recovery.name);
    setDescription(recovery.description);
    setGraph(recovery.graph);
    setRecovery(null);
    setConflict(false);
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
    if (dirty) {
      setConfirmLeave(true);
      return;
    }
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
        <ErrorInline message={error} className="mb-4" />
        <div className="panel max-w-xl space-y-4 p-5">
          <Field label="Nombre" required>
            <Input
              placeholder="Alerta de stock bajo"
              value={name}
              onChange={(e) => setName(e.target.value)}
              data-testid="wf-new-name"
            />
          </Field>
          <Field label="Qué hace (opcional)" hint="Una línea sobre el resultado, no sobre la implementación.">
            <Input
              placeholder="Avisa al equipo cuando queden menos de 5 unidades"
              value={description}
              onChange={(e) => setDescription(e.target.value)}
            />
          </Field>
          <FormActions className="justify-start">
            <Button
              variant="primary"
              loading={saving}
              leadingIcon={Lightning}
              disabled={!name.trim()}
              onClick={() => void create()}
              data-testid="wf-create"
            >
              Crear y abrir el lienzo
            </Button>
            <Button variant="ghost" leadingIcon={ArrowLeft} onClick={back}>
              Volver
            </Button>
          </FormActions>
        </div>
      </div>
    );
  }

  return (
    // El shell pone la ruta en modo full-bleed (ver `fullBleed` en App.tsx):
    // aquí solo repartimos la altura entre cabecera, lienzo y dock.
    <div className="flex min-h-0 min-w-0 flex-1 flex-col gap-2">
      <header className="flex flex-wrap items-center gap-x-3 gap-y-2 border-b border-border pb-3">
        <IconButton
          label="Volver a workflows"
          icon={ArrowLeft}
          className="shrink-0"
          onClick={back}
        />
        <div className="min-w-[12rem] flex-1">
          <Input
            className="h-9 border-transparent bg-transparent px-1.5 text-[17px] font-semibold hover:border-border focus:border-border focus:bg-soft"
            value={name}
            onChange={(e) => setName(e.target.value)}
            aria-label="Nombre del workflow"
            data-testid="wf-name"
          />
          <Input
            className="h-8 border-transparent bg-transparent px-1.5 text-xs text-muted hover:border-border focus:border-border focus:bg-soft"
            value={description}
            placeholder="Añade una descripción corta"
            onChange={(e) => setDescription(e.target.value)}
            aria-label="Descripción del workflow"
          />
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <SaveStatus state={saveIndicator} error={saveError || undefined} dirtyLabel="Cambios sin guardar" />
          <StatusBadge status={status} />
          <span data-testid="wf-active-toggle" className="inline-flex items-center">
            <Switch
              checked={status === "active"}
              disabled={statusBusy}
              onCheckedChange={(checked) => void toggleStatus(checked)}
              label="Activo"
            />
          </span>
          <Button
            variant="ghost"
            size="sm"
            leadingIcon={ArrowCounterClockwise}
            disabled={!historyState.canUndo}
            onClick={undo}
            title="Deshacer (Ctrl+Z)"
            aria-label="Deshacer"
            data-testid="wf-undo"
          >
            Deshacer
          </Button>
          <Button
            variant="ghost"
            size="sm"
            leadingIcon={ArrowClockwise}
            disabled={!historyState.canRedo}
            onClick={redo}
            title="Rehacer (Ctrl+Shift+Z)"
            aria-label="Rehacer"
            data-testid="wf-redo"
          >
            Rehacer
          </Button>
          <Button variant="secondary" size="sm" leadingIcon={Code} onClick={() => openDrawer("api")} data-testid="wf-open-api">
            API
          </Button>
          <Button
            variant="secondary"
            size="sm"
            leadingIcon={SlidersHorizontal}
            onClick={() => openDrawer("advanced")}
            data-testid="wf-open-advanced"
          >
            Avanzado
          </Button>
          <Button
            variant="secondary"
            size="sm"
            leadingIcon={Brain}
            onClick={() => openDrawer("memory")}
            data-testid="wf-open-memory"
          >
            Memoria
          </Button>
          <Button
            variant="secondary"
            size="sm"
            leadingIcon={Lightning}
            onClick={() => openDrawer("library")}
            data-testid="wf-open-library"
          >
            Subflujos
          </Button>
          <Button variant="secondary" size="sm" leadingIcon={MagicWand} onClick={() => setPatchOpen(true)} data-testid="wf-open-patch">
            Editar con IA
          </Button>
          <ButtonLink
            to={`/chat?target=workflow&id=${id}`}
            variant="ghost"
            size="sm"
            leadingIcon={ChatCircleDots}
          >
            Probar en Playground
          </ButtonLink>
          <Button
            variant="ghost"
            size="sm"
            className="lg:hidden"
            aria-expanded={dockOpen}
            onClick={() => {
              // Deja terminar el click antes de montar el overlay del drawer.
              window.setTimeout(() => setDockOpen(true), 0);
            }}
            data-testid="wf-open-dock"
          >
            Probar
          </Button>
          <Button
            variant="primary"
            size="sm"
            loading={saving}
            leadingIcon={FloppyDisk}
            disabled={!name.trim()}
            onClick={() => void save()}
            data-testid="wf-save"
            title="Guardar cambios en el borrador; no publica ni despliega."
          >
            Guardar borrador
          </Button>
        </div>
      </header>

      {msg && <InlineFlash className="shrink-0">{msg}</InlineFlash>}
      {error && <ErrorInline message={error} className="mb-0 shrink-0" />}
      {conflict && (
        <div className="flex flex-wrap items-center gap-2 rounded-md border border-warn/40 bg-warn-soft px-3 py-2 text-[13px]" role="status" data-testid="wf-conflict">
          <span className="min-w-0 flex-1">Otra pestaña guardó este flujo. Tus cambios no se borraron.</span>
          <Button size="sm" variant="secondary" data-testid="wf-conflict-keep" onClick={() => setConflict(false)}>
            Seguir con mis cambios
          </Button>
          <Button
            size="sm"
            variant="ghost"
            data-testid="wf-conflict-reload"
            onClick={() => {
              setConflict(false);
              void load(true);
            }}
          >
            Cargar la versión del servidor
          </Button>
        </div>
      )}
      {recovery && (
        <div className="flex flex-wrap items-center gap-2 rounded-md border border-border bg-soft px-3 py-2 text-[13px]" role="status" data-testid="wf-recovery">
          <span className="min-w-0 flex-1">Hay cambios locales de un guardado que no llegó al servidor.</span>
          <Button size="sm" variant="secondary" data-testid="wf-recovery-apply" onClick={applyRecovery}>
            Recuperar mis cambios
          </Button>
          <Button
            size="sm"
            variant="ghost"
            onClick={() => {
              if (id) sessionStorage.removeItem(draftKey(id));
              setRecovery(null);
            }}
          >
            Descartar
          </Button>
        </div>
      )}

      {graph && (
        <details className="shrink-0" data-testid="wf-mission-disclosure">
          <summary className="cursor-pointer text-[13px] font-medium text-text">Ficha de misión</summary>
          <div className="mt-2">
            <MissionCard value={missionFromGraph(graph.metadata)} onChange={updateMission} />
          </div>
        </details>
      )}

      {id && <WorkflowHealthBar workflowId={id} refreshKey={detail?.updated_at ?? ""} />}

      {/* Embudo de ventas: checklist de configuración y KPIs del proceso vivo. */}
      {id && isSalesFunnel(graph) && (
        <div className="grid shrink-0 gap-3 xl:grid-cols-2" data-testid="funnel-panels">
          <SalesFunnelChecklist />
          <SalesFunnelKpis />
        </div>
      )}

      <div className="flex min-h-0 flex-1 gap-3">
        <div className="min-w-0 flex-1">
          <WorkflowCanvasEditor
            heightClass="h-full"
            workflowId={id ?? null}
            graph={graph}
            onChangeGraph={(g) => commitGraph(structuredClone(g))}
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
        {id && isDesktop && (
          <aside className="flex min-h-0 w-80 shrink-0 flex-col xl:w-[22rem]">
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
      {id && !isDesktop && (
        <Drawer
          open={dockOpen}
          onOpenChange={setDockOpen}
          title="Probar"
          description="Simula y ejecuta el flujo sin salir del lienzo."
          side="bottom"
          keepMounted
        >
          <div className="grid h-[66dvh] w-full max-w-3xl" data-testid="wf-dock-sheet">
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
              embedded
            />
          </div>
        </Drawer>
      )}

      {drawer && id && (
        <Drawer
          open
          onOpenChange={(open) => {
            if (!open) openDrawer(null);
          }}
          title={STUDIO_DRAWER_LABELS[drawer]}
          description={
            drawer === "api"
              ? "Dispara este workflow desde cualquier sistema con un POST autenticado."
              : "Snapshots, publicación y restauración del grafo y el trigger."
          }
          width={drawer === "api" ? 600 : 560}
        >
          <div className="space-y-4" data-testid={`wf-drawer-${drawer}`}>
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
            ) : drawer === "memory" ? (
              <AgentMemoryPanel agents={agents} />
            ) : drawer === "library" ? (
              <SubflowLibraryPanel
                onInsert={(subflow) => {
                  const node: GraphNode = {
                    id: newGraphNodeId(),
                    type: "subworkflow_call",
                    version: 1,
                    label: subflow.name,
                    position: { x: 160, y: 160 },
                    config: subflow.node_config,
                    input_ports: [{ name: "in", type: "json" }],
                    output_ports: [{ name: "out", type: "json" }],
                    retry_policy: { max_attempts: 1 },
                    timeout_ms: 60000,
                    error_policy: "fail",
                    metadata: { subflow: subflow.name, version: subflow.version },
                  };
                  const current = graphRef.current ?? graph;
                  commitGraph(
                    current
                      ? { ...current, nodes: [...current.nodes, node] }
                      : {
                          workflow_version: 2,
                          nodes: [node],
                          edges: [],
                          variables: {},
                          entrypoints: [],
                          metadata: {},
                        }
                  );
                  setSelectedNode(node.id);
                  openDrawer(null);
                }}
              />
            ) : (
              <WorkflowVersionsPanel workflowId={id} status={status} onChanged={() => void load(true)} />
            )}
            <Button variant="ghost" className="w-full" onClick={() => openDrawer(null)}>
              Cerrar
            </Button>
          </div>
        </Drawer>
      )}

      {id && (
        <Drawer
          open={patchOpen}
          onOpenChange={setPatchOpen}
          title="Editar con IA"
          description="Pide el cambio en lenguaje natural; Zent te muestra el diff antes de aplicar."
          width={520}
        >
          <div data-testid="wf-patch-drawer">
            <WorkflowPatchPanel
              workflowId={id}
              onClose={() => setPatchOpen(false)}
              onApplied={() => {
                setPatchOpen(false);
                void load(true);
              }}
            />
          </div>
        </Drawer>
      )}

      <ConfirmDialog
        open={confirmLeave}
        onOpenChange={setConfirmLeave}
        title="Hay cambios sin guardar"
        body="Si sales ahora, el lienzo vuelve a la última versión guardada."
        confirmLabel="Salir sin guardar"
        cancelLabel="Seguir editando"
        onConfirm={() => {
          setConfirmLeave(false);
          navigate("/workflows");
        }}
      />
    </div>
  );
}
