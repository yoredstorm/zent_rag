import {
  ArrowClockwise,
  ArrowCounterClockwise,
  ArrowLeft,
  ArrowsIn,
  ArrowsOut,
  Brain,
  ChartBar,
  ChatCircleDots,
  CircleNotch,
  Code,
  CornersIn,
  DotsThreeVertical,
  FloppyDisk,
  Lightning,
  MagicWand,
  Play,
  RocketLaunch,
  Target,
  X,
} from "@phosphor-icons/react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useLocation, useNavigate, useParams, useSearchParams } from "react-router-dom";
import { api } from "../api";
import { isApiError } from "../lib/errors";
import { useMediaQuery } from "../lib/useMediaQuery";
import { useAuth } from "../auth";
import { useToast } from "../Toast";
import { Breadcrumb } from "../components/Breadcrumb";
import {
  Badge,
  Button,
  ConfirmDialog,
  Drawer,
  ErrorInline,
  Field,
  FormActions,
  IconButton,
  Input,
  Menu,
  MenuItem,
  MenuSeparator,
  PageHeader,
  SkeletonBlock,
  Switch,
  Tooltip,
  menuItemClass,
  menuSeparatorClass,
} from "../components/ui";
import { WorkflowCanvasEditor } from "../components/WorkflowCanvasEditor";
import type { CanvasChangeOptions, CanvasHandle, RunOverlay } from "../components/WorkflowCanvas";
import type { RunDetail } from "../components/WorkflowRunInspector";
import { SimulatorDock, type SimulatorState } from "../components/workflowStudio/SimulatorDock";
import { viewportStorageKey, type Viewport } from "../lib/canvasViewport";
import { hasUnpublishedChanges, lifecycleIndicator, missionSummary, persistenceIndicator } from "../lib/studioState";
import { loadStudioPrefs, saveStudioPrefs, type StudioPrefs } from "../lib/studioLayout";
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
  layoutGraph,
  newGraphNodeId,
  nodeMeta,
  prepareGraphForSave,
  triggerConfigOf,
  triggerTypeOf,
} from "../lib/workflowGraph";

type StudioState = { hookSecret?: string };

const PERSISTENCE_DOT: Record<string, string> = {
  dirty: "bg-warn",
  error: "bg-danger",
  saved: "bg-ok",
  clean: "bg-faint",
};

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
  const canvasRef = useRef<CanvasHandle | null>(null);
  const [prefs, setPrefs] = useState<StudioPrefs>(loadStudioPrefs);
  /** Simulador acoplado (desktop). Una vez abierto queda montado para no perder la prueba. */
  const [simulator, setSimulator] = useState<SimulatorState>("closed");
  const [simulatorMounted, setSimulatorMounted] = useState(false);
  const [focusMode, setFocusMode] = useState(false);
  const focusSnapshot = useRef<{ simulator: SimulatorState; viewport: Viewport | null } | null>(null);
  const [missionOpen, setMissionOpen] = useState(false);
  const [funnelOpen, setFunnelOpen] = useState(false);
  const [viewportH, setViewportH] = useState(() => window.innerHeight);
  const { pushToast } = useToast();

  const status = detail?.status ?? "draft";

  useEffect(() => {
    saveStudioPrefs(prefs);
  }, [prefs]);

  useEffect(() => {
    const onResize = () => setViewportH(window.innerHeight);
    window.addEventListener("resize", onResize);
    return () => window.removeEventListener("resize", onResize);
  }, []);

  const openSimulator = useCallback(() => {
    if (!isDesktop) {
      // Deja terminar el click antes de montar el overlay del drawer.
      window.setTimeout(() => setDockOpen(true), 0);
      return;
    }
    setSimulatorMounted(true);
    setSimulator("open");
  }, [isDesktop]);

  useEffect(() => {
    if (panel !== "test") return;
    if (isDesktop) {
      setSimulatorMounted(true);
      setSimulator("open");
    } else setDockOpen(true);
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
  const persistence = persistenceIndicator({ dirty, saving, saveError, justSaved: saveFlash === "saved" });
  const lifecycle = lifecycleIndicator({
    status,
    publishedVersion: detail?.published_version_number,
    draftChanged: detail?.draft_changed,
    dirty,
  });
  const unpublished = hasUnpublishedChanges({ status, draftChanged: detail?.draft_changed, dirty });

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
    const g = layoutGraph(d.graph ?? starterGraph());
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

  // Confirmaciones como toast: un banner fijo le roba alto al lienzo.
  useEffect(() => {
    if (!msg) return;
    pushToast("success", msg);
    setMsg("");
  }, [msg, pushToast]);

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

  const commitGraph = useCallback((next: WorkflowGraph, options?: CanvasChangeOptions) => {
    const previous = graphRef.current ?? graph;
    if (previous) {
      const now = Date.now();
      // Ráfagas (teclear, flechas) se agrupan en un paso; un checkpoint
      // (soltar un arrastre, organizar, conectar) siempre es su propio paso.
      if (options?.checkpoint || now - historyStampRef.current > 350) {
        historyRef.current.past.push(structuredClone(previous));
        if (historyRef.current.past.length > 40) historyRef.current.past.shift();
        historyRef.current.future = [];
        historyStampRef.current = options?.checkpoint ? 0 : now;
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
    setGraph(layoutGraph(recovery.graph));
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
        if (isDesktop) {
          setSimulatorMounted(true);
          setSimulator((current) => (current === "closed" ? "open" : current));
        }
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
    window.setTimeout(() => canvasRef.current?.centerNode(nodeId), 0);
  }

  /** Un resultado del simulador lleva a su nodo: lo selecciona y lo centra. */
  const focusNodeFromRun = useCallback((nodeId: string) => {
    setSelectedNode(nodeId);
    canvasRef.current?.centerNode(nodeId);
  }, []);

  const enterFocus = useCallback(() => {
    focusSnapshot.current = { simulator, viewport: canvasRef.current?.getViewport() ?? null };
    setFocusMode(true);
  }, [simulator]);

  const exitFocus = useCallback(() => {
    const snapshot = focusSnapshot.current;
    focusSnapshot.current = null;
    setFocusMode(false);
    if (document.fullscreenElement) void document.exitFullscreen().catch(() => undefined);
    if (snapshot) {
      setSimulator(snapshot.simulator);
      if (snapshot.viewport) {
        const view = snapshot.viewport;
        window.requestAnimationFrame(() => canvasRef.current?.setViewport(view));
      }
    }
  }, []);

  // F alterna el modo enfoque; Esc sale (si el lienzo no usó el Esc para cerrar algo).
  useEffect(() => {
    function onKey(event: KeyboardEvent) {
      const target = event.target as HTMLElement | null;
      const inOverlay = Boolean(target?.closest?.('[role="dialog"],[role="menu"],[role="listbox"]'));
      if (event.key === "Escape" && focusMode && !inOverlay) {
        window.setTimeout(() => {
          if (!event.defaultPrevented) exitFocus();
        }, 0);
        return;
      }
      const editing =
        target?.tagName === "INPUT" || target?.tagName === "TEXTAREA" || target?.tagName === "SELECT" || target?.isContentEditable;
      if (editing || inOverlay || event.ctrlKey || event.metaKey || event.altKey) return;
      if (event.key === "f" || event.key === "F") {
        event.preventDefault();
        if (focusMode) exitFocus();
        else enterFocus();
      }
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [focusMode, enterFocus, exitFocus]);

  function toggleNativeFullscreen() {
    if (document.fullscreenElement) void document.exitFullscreen().catch(() => undefined);
    else void document.documentElement.requestFullscreen?.().catch(() => undefined);
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

  const mission = graph ? missionSummary(missionFromGraph(graph.metadata)) : "";

  const focusToolbarExtra = focusMode ? (
    <>
      <Tooltip label="Salir del modo enfoque · Esc">
        <button
          type="button"
          aria-label="Salir del modo enfoque"
          data-testid="wf-focus-exit"
          onClick={exitFocus}
          className="flex h-8 cursor-pointer items-center gap-1.5 rounded-md px-2 text-[12px] font-medium text-text outline-none hover:bg-soft focus-visible:ring-2 focus-visible:ring-accent"
        >
          <ArrowsIn size={15} aria-hidden /> Salir
        </button>
      </Tooltip>
      <Tooltip label="Pantalla completa del navegador (opcional)">
        <button
          type="button"
          aria-label="Pantalla completa del navegador"
          onClick={toggleNativeFullscreen}
          className="flex h-8 w-8 cursor-pointer items-center justify-center rounded-md text-muted outline-none hover:bg-soft hover:text-text focus-visible:ring-2 focus-visible:ring-accent"
        >
          <CornersIn size={15} aria-hidden />
        </button>
      </Tooltip>
    </>
  ) : null;

  const simulatorDock =
    id && isDesktop && simulatorMounted ? (
      <SimulatorDock
        state={simulator}
        onStateChange={setSimulator}
        height={prefs.simulatorHeight}
        onHeightChange={(height) => setPrefs((p) => ({ ...p, simulatorHeight: height }))}
        availableHeight={viewportH - 100}
        run={run}
      >
        <WorkflowTestPanel
          workflowId={id}
          status={status}
          effectLabels={effectLabels}
          issues={issues}
          dirty={dirty}
          onRun={setRun}
          onSelectNode={focusNodeFromRun}
          onRan={() => void load(true)}
          onSaveBeforeRun={save}
          graph={graph}
          graphHash={detail?.graph_hash}
          embedded
          split
        />
      </SimulatorDock>
    ) : null;

  return (
    // El shell pone la ruta en modo full-bleed (ver `studioCanvas` en App.tsx).
    // Modo enfoque: el estudio cubre la navegación (no usa la Fullscreen API).
    <div
      className={
        focusMode
          ? "fixed inset-0 z-[35] flex min-h-0 min-w-0 flex-col bg-bg"
          : "flex min-h-0 min-w-0 flex-1 flex-col"
      }
      data-testid="wf-studio"
      data-focus={focusMode ? "true" : "false"}
    >
      <header
        className={`flex h-12 shrink-0 items-center gap-1.5 border-b border-border bg-surface px-2 ${focusMode ? "hidden" : ""}`}
        data-testid="wf-studio-header"
      >
        <IconButton label="Volver a workflows" icon={ArrowLeft} iconSize={16} className="h-8 w-8 shrink-0" onClick={back} />
        <Input
          className="h-8 w-[clamp(10rem,16vw,17rem)] min-w-[7rem] shrink border-transparent bg-transparent px-1.5 text-[15px] font-semibold hover:border-border focus:border-border focus:bg-soft"
          value={name}
          onChange={(e) => setName(e.target.value)}
          aria-label="Nombre del workflow"
          data-testid="wf-name"
        />
        <Tooltip label={mission ? `Misión: ${mission}` : "Define el objetivo, el público y los límites del flujo"}>
          <button
            type="button"
            className="inline-flex h-8 min-w-0 max-w-[clamp(6rem,22vw,24rem)] shrink cursor-pointer items-center gap-1.5 rounded-md border border-border px-2 text-[12px] text-muted outline-none hover:border-border-strong hover:text-text focus-visible:ring-2 focus-visible:ring-accent"
            onClick={() => setMissionOpen(true)}
            data-testid="wf-mission-summary"
            aria-haspopup="dialog"
            aria-label={mission ? `Misión: ${mission}` : "Definir misión"}
          >
            <Target size={14} className="shrink-0 text-accent" aria-hidden />
            <span className="hidden truncate xl:inline">{mission || "Definir misión"}</span>
          </button>
        </Tooltip>
        <span className="min-w-2 flex-1" />

        <div className="flex shrink-0 items-center gap-1.5" data-testid="wf-studio-status">
          <Tooltip label={persistence.detail ?? persistence.label}>
            <span
              className="inline-flex h-8 items-center gap-1.5 px-1 text-[12px] text-muted"
              data-testid="wf-persistence"
              data-state={persistence.key}
              role="status"
              aria-live="polite"
              aria-label={persistence.label}
            >
              {persistence.key === "saving" ? (
                <CircleNotch size={13} className="animate-spin text-info" aria-hidden />
              ) : (
                <span className={`h-2 w-2 rounded-full ${PERSISTENCE_DOT[persistence.key] ?? "bg-faint"}`} aria-hidden />
              )}
              <span className="hidden whitespace-nowrap xl:inline">{persistence.label}</span>
            </span>
          </Tooltip>
          <span data-testid="wf-lifecycle" data-state={lifecycle.key} title={lifecycle.detail}>
            <Badge tone={lifecycle.tone} dot className="whitespace-nowrap">
              {lifecycle.label}
            </Badge>
          </span>
          {id && <WorkflowHealthBar workflowId={id} refreshKey={detail?.updated_at ?? ""} variant="chip" />}
          <span data-testid="wf-active-toggle" className="ml-1 inline-flex items-center" title="Activa o pausa la versión publicada">
            <Switch
              checked={status === "active"}
              disabled={statusBusy}
              onCheckedChange={(checked) => void toggleStatus(checked)}
              label="Activo"
            />
          </span>
        </div>

        <span className="mx-1 h-5 w-px shrink-0 bg-border" aria-hidden />
        <div className="flex shrink-0 items-center gap-1">
          <IconButton
            label="Deshacer (Ctrl+Z)"
            icon={ArrowCounterClockwise}
            iconSize={16}
            className="h-8 w-8"
            disabled={!historyState.canUndo}
            onClick={undo}
            aria-label="Deshacer"
            data-testid="wf-undo"
          />
          <IconButton
            label="Rehacer (Ctrl+Shift+Z)"
            icon={ArrowClockwise}
            iconSize={16}
            className="h-8 w-8"
            disabled={!historyState.canRedo}
            onClick={redo}
            aria-label="Rehacer"
            data-testid="wf-redo"
          />
          <Button
            variant="secondary"
            size="sm"
            leadingIcon={Play}
            aria-expanded={isDesktop ? simulator === "open" : dockOpen}
            onClick={() => (isDesktop && simulator === "open" ? setSimulator("collapsed") : openSimulator())}
            data-testid="wf-open-dock"
            title="Abrir el simulador bajo el lienzo"
          >
            Probar
          </Button>
          <Button
            variant="secondary"
            size="sm"
            leadingIcon={RocketLaunch}
            onClick={() => openDrawer("advanced")}
            data-testid="wf-open-advanced"
            title={unpublished ? "Hay cambios del borrador sin publicar" : "Versiones y publicación"}
            className="relative"
          >
            <span className="hidden xl:inline">Publicar</span>
            {unpublished && <span className="absolute -top-0.5 -right-0.5 h-2 w-2 rounded-full bg-warn" aria-label="cambios sin publicar" />}
          </Button>
          <Button
            variant="primary"
            size="sm"
            loading={saving}
            leadingIcon={FloppyDisk}
            disabled={!name.trim()}
            onClick={() => void save()}
            data-testid="wf-save"
            title="Guardar cambios en el borrador (Ctrl+S); no publica ni despliega."
          >
            Guardar
          </Button>
          <Menu
            label="Más acciones del workflow"
            trigger={
              <button
                type="button"
                aria-label="Más acciones"
                title="Más acciones"
                className="btn btn-ghost btn-icon h-8 w-8"
                data-testid="wf-more"
              >
                <DotsThreeVertical size={17} aria-hidden />
              </button>
            }
          >
            <MenuItem className={menuItemClass} onSelect={() => openDrawer("api")} data-testid="wf-open-api">
              <Code size={15} aria-hidden /> API
            </MenuItem>
            <MenuItem className={menuItemClass} onSelect={() => openDrawer("memory")} data-testid="wf-open-memory">
              <Brain size={15} aria-hidden /> Memoria del agente
            </MenuItem>
            <MenuItem className={menuItemClass} onSelect={() => openDrawer("library")} data-testid="wf-open-library">
              <Lightning size={15} aria-hidden /> Subflujos
            </MenuItem>
            <MenuItem className={menuItemClass} onSelect={() => setPatchOpen(true)} data-testid="wf-open-patch">
              <MagicWand size={15} aria-hidden /> Editar con IA
            </MenuItem>
            <MenuItem className={menuItemClass} onSelect={() => navigate(`/chat?target=workflow&id=${id}`)}>
              <ChatCircleDots size={15} aria-hidden /> Probar en Playground
            </MenuItem>
            {isSalesFunnel(graph) && (
              <MenuItem className={menuItemClass} onSelect={() => setFunnelOpen(true)} data-testid="wf-open-funnel">
                <ChartBar size={15} aria-hidden /> Embudo de ventas
              </MenuItem>
            )}
            <MenuSeparator className={menuSeparatorClass} />
            <MenuItem className={menuItemClass} onSelect={enterFocus}>
              <ArrowsOut size={15} aria-hidden /> Modo enfoque
              <kbd className="ml-auto text-[11px] text-faint">F</kbd>
            </MenuItem>
          </Menu>
          <IconButton
            label="Modo enfoque (F)"
            icon={ArrowsOut}
            iconSize={16}
            className="h-8 w-8"
            onClick={enterFocus}
            data-testid="wf-focus-toggle"
          />
        </div>
      </header>

      <div className="relative flex min-h-0 min-w-0 flex-1">
        <WorkflowCanvasEditor
          heightClass="h-full flex-1"
          workflowId={id ?? null}
          graph={graph}
          onChangeGraph={(g, _tt, _tc, options) => commitGraph(structuredClone(g), options)}
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
          canvasRef={canvasRef}
          viewportKey={id && session ? viewportStorageKey(session.email || session.organizationId, id) : null}
          bottomPanel={simulatorDock}
          chrome={focusMode ? "focus" : "full"}
          toolbarExtra={focusToolbarExtra}
          inspectorWidth={prefs.inspectorWidth}
          onInspectorWidthChange={(width) => setPrefs((p) => ({ ...p, inspectorWidth: width }))}
          minimap={prefs.minimap}
          onToggleMinimap={() => setPrefs((p) => ({ ...p, minimap: !p.minimap }))}
          onExitFocus={exitFocus}
        />

        {/* Avisos flotantes: no empujan el lienzo. */}
        <div
          className="pointer-events-none absolute top-3 left-1/2 z-30 flex w-[min(560px,calc(100%-9rem))] -translate-x-1/2 flex-col gap-2 [&>*]:pointer-events-auto"
          aria-live="polite"
        >
      {error && (
        <div className="flex items-start gap-1 rounded-md bg-surface shadow-pop" data-testid="wf-error">
          <ErrorInline message={error} className="mb-0 min-w-0 flex-1" />
          <IconButton label="Cerrar aviso" icon={X} iconSize={14} className="h-8 w-8" onClick={() => setError("")} />
        </div>
      )}
      {conflict && (
        <div className="flex flex-wrap items-center gap-2 rounded-md border border-warn/40 bg-warn-soft px-3 py-2 text-[13px] shadow-pop" role="status" data-testid="wf-conflict">
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
        <div className="flex flex-wrap items-center gap-2 rounded-md border border-border bg-raised px-3 py-2 text-[13px] shadow-pop" role="status" data-testid="wf-recovery">
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
        </div>
      </div>

      {graph && (
        <Drawer
          open={missionOpen}
          onOpenChange={setMissionOpen}
          title="Ficha de misión"
          description="Qué hace el flujo, para quién y con qué límites. Viaja con el lienzo."
          width={560}
        >
          <div className="space-y-4" data-testid="wf-mission-drawer">
            <Field label="Qué hace" hint="Una línea sobre el resultado, no sobre la implementación.">
              <Input
                value={description}
                placeholder="Añade una descripción corta"
                onChange={(e) => setDescription(e.target.value)}
                aria-label="Descripción del workflow"
              />
            </Field>
            <MissionCard value={missionFromGraph(graph.metadata)} onChange={updateMission} />
          </div>
        </Drawer>
      )}

      {/* Embudo de ventas: checklist de configuración y KPIs del proceso vivo. */}
      {id && isSalesFunnel(graph) && (
        <Drawer
          open={funnelOpen}
          onOpenChange={setFunnelOpen}
          title="Embudo de ventas"
          description="Checklist de configuración y KPIs del proceso vivo."
          width={640}
        >
          <div className="grid gap-3" data-testid="funnel-panels">
            <SalesFunnelChecklist />
            <SalesFunnelKpis />
          </div>
        </Drawer>
      )}

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
              graphHash={detail?.graph_hash}
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
