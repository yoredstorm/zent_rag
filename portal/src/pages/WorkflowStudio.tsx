import { ArrowLeft, ChatCircleDots, Code, FloppyDisk, Lightning, MagicWand, SlidersHorizontal } from "@phosphor-icons/react";
import { useCallback, useEffect, useMemo, useState } from "react";
import { useLocation, useNavigate, useParams, useSearchParams } from "react-router-dom";
import { api } from "../api";
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
import { WorkflowApiPanel } from "../components/workflowStudio/WorkflowApiPanel";
import { WorkflowHealthBar } from "../components/workflowStudio/WorkflowHealthBar";
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
  // El dock de prueba es la hoja móvil: en desktop el panel ya vive en la columna derecha,
  // así que `?panel=test` no debe abrir un scrim que bloquee el lienzo.
  const [dockOpen, setDockOpen] = useState(
    panel === "test" &&
      typeof window !== "undefined" &&
      !window.matchMedia("(min-width: 1024px)").matches
  );
  const [patchOpen, setPatchOpen] = useState(false);
  const [pinnedNodes, setPinnedNodes] = useState<string[]>([]);
  const [partialBusy, setPartialBusy] = useState("");
  /** Feedback de persistencia: guardado reciente / error de guardado. */
  const [saveFlash, setSaveFlash] = useState<"idle" | "saved">("idle");
  const [saveError, setSaveError] = useState("");
  const [confirmLeave, setConfirmLeave] = useState(false);

  const status = detail?.status ?? "draft";

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
      await load(true);
      return true;
    } catch (e) {
      const message = e instanceof Error ? e.message : "Error";
      setError(message);
      setSaveError(message);
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
    <div className="flex h-[calc(100dvh-5.5rem)] min-h-[34rem] min-w-0 flex-col gap-2 lg:h-[calc(100dvh-1.5rem)]">
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
            onClick={() => setDockOpen(true)}
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
          >
            Guardar
          </Button>
        </div>
      </header>

      {msg && <InlineFlash className="shrink-0">{msg}</InlineFlash>}
      {error && <ErrorInline message={error} className="mb-0 shrink-0" />}

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
      {id && (
        <Drawer
          open={dockOpen}
          onOpenChange={setDockOpen}
          title="Probar"
          description="Simula y ejecuta el flujo sin salir del lienzo."
          side="bottom"
          className="lg:hidden"
          overlayClassName="lg:hidden"
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
