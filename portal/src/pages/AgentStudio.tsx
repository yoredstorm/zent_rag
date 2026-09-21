import { ArrowLeft, ChatCircleDots, FloppyDisk } from "@phosphor-icons/react";
import { FormEvent, useEffect, useMemo, useRef, useState } from "react";
import { Link, useLocation, useNavigate, useParams, useSearchParams } from "react-router-dom";
import { api } from "../api";
import { useAuth } from "../auth";
import { AgentAdvancedPanel } from "../components/agentStudio/AgentAdvancedPanel";
import { AgentPurposeForm } from "../components/agentStudio/AgentPurposeForm";
import { AgentSourcePicker, AGENT_SOURCE_CAP_MSG, MAX_AGENT_SOURCES } from "../components/agentStudio/AgentSourcePicker";
import { AgentTestChat, type ChatTurn } from "../components/agentStudio/AgentTestChat";
import { hasDbSources, sourceTypesForSelection } from "../components/agentStudio/toolApplicability";
import { flowFromAgentSteps } from "./chat/runPlaygroundTurn";
import {
  type AdvancedTab,
  type Agent,
  type AgentVersion,
  type Deployment,
  type Environment,
  type IngestionJob,
  type KnowledgeSource,
  type AgentConfig,
  defaultConfig,
  legacyTabToGroup,
  sourceIdsFromSteps,
  toolErrorsFromSteps,
  buildAgentPayload,
} from "../components/agentStudio/types";
import { Breadcrumb } from "../components/Breadcrumb";
import {
  Button,
  ConfirmDialog,
  ErrorInline,
  PageHeader,
  Panel,
  PanelHeader,
  SaveStatus,
  SkeletonBlock,
  SuccessInline,
  Switch,
  type SaveState,
} from "../components/ui";

type StudioLocationState = { pendingMessage?: string };

export default function AgentStudioPage() {
  const { id } = useParams<{ id: string }>();
  const isNew = !id || id === "new";
  const navigate = useNavigate();
  const location = useLocation();
  const [searchParams, setSearchParams] = useSearchParams();
  const { session } = useAuth();
  const panel = searchParams.get("panel") === "test" ? "test" : "configure";
  const tabGroup = legacyTabToGroup(searchParams.get("tab"));
  const advancedTab: AdvancedTab = tabGroup ?? "behavior";
  const advancedOpen = searchParams.get("panel") === "advanced" || tabGroup !== null;

  const [sources, setSources] = useState<KnowledgeSource[]>([]);
  const [jobs, setJobs] = useState<IngestionJob[]>([]);
  const [sourcesLoading, setSourcesLoading] = useState(true);
  const [indexingId, setIndexingId] = useState("");
  const [name, setName] = useState("");
  const [systemPrompt, setSystemPrompt] = useState("");
  const [model, setModel] = useState("zent-default");
  const [routes, setRoutes] = useState<{ name: string; description: string }[]>([]);
  const [canCustomModel, setCanCustomModel] = useState(false);
  const [config, setConfig] = useState(defaultConfig());
  const [semantic, setSemantic] = useState(true);
  const [sql, setSql] = useState(true);
  const [apiCalls, setApiCalls] = useState(true);
  const [jevMode, setJevMode] = useState<"inherit" | "on" | "off">("inherit");
  const [answerGate, setAnswerGate] = useState<"inherit" | "on" | "off">("inherit");
  const [isActive, setIsActive] = useState(true);
  const [loading, setLoading] = useState(!isNew);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const [msg, setMsg] = useState("");
  const [playInput, setPlayInput] = useState("");
  const [turns, setTurns] = useState<ChatTurn[]>([]);
  const [playStatus, setPlayStatus] = useState("");
  const [playing, setPlaying] = useState(false);
  const [embedOrigins, setEmbedOrigins] = useState("https://");
  const [embedScript, setEmbedScript] = useState("");
  const [embedToken, setEmbedToken] = useState("");
  const [embedBusy, setEmbedBusy] = useState(false);
  const [versions, setVersions] = useState<AgentVersion[]>([]);
  const [environments, setEnvironments] = useState<Environment[]>([]);
  const [deployments, setDeployments] = useState<Deployment[]>([]);
  const [versionsLoading, setVersionsLoading] = useState(false);
  const [deployError, setDeployError] = useState("");
  const [deployMsg, setDeployMsg] = useState("");
  const [deployVersionId, setDeployVersionId] = useState("");
  const [deployEnvId, setDeployEnvId] = useState("");
  const [deployBusy, setDeployBusy] = useState(false);
  const [eventsFor, setEventsFor] = useState<{
    deploymentId: string;
    events: { event: string; created_at: string | null; metadata: Record<string, unknown> }[];
  } | null>(null);
  const [retrieval, setRetrieval] = useState({ strategy: "hybrid", top_k: 10, score_threshold: 0.0 });
  const [outputSchema, setOutputSchema] = useState("");
  const [readiness, setReadiness] = useState<{
    score: number;
    items: { key: string; label: string; met: boolean; weight: number; detail: string }[];
  } | null>(null);
  const [workspaceId, setWorkspaceId] = useState("");
  const [savedPayload, setSavedPayload] = useState("");
  const [nameTouched, setNameTouched] = useState(false);
  const [leaveOpen, setLeaveOpen] = useState(false);
  const pendingRun = useRef<string | null>(null);

  const payload = useMemo(
    () =>
      buildAgentPayload({
        name,
        systemPrompt,
        model,
        semantic,
        sql,
        apiCalls,
        isActive,
        config,
        retrieval,
        outputSchema,
        workspaceId,
      }),
    [name, systemPrompt, model, semantic, sql, apiCalls, isActive, config, retrieval, outputSchema, workspaceId],
  );

  const dirty = !isNew && savedPayload !== "" && JSON.stringify(payload) !== savedPayload;

  useEffect(() => {
    if (!dirty) return;
    function onBeforeUnload(event: BeforeUnloadEvent) {
      event.preventDefault();
      event.returnValue = "";
    }
    window.addEventListener("beforeunload", onBeforeUnload);
    return () => window.removeEventListener("beforeunload", onBeforeUnload);
  }, [dirty]);

  const sourcesRef = useRef<KnowledgeSource[]>([]);
  const jobsRef = useRef<IngestionJob[]>([]);
  sourcesRef.current = sources;
  jobsRef.current = jobs;

  useEffect(() => {
    if (!session) return;
    let cancelled = false;

    async function refresh(initial: boolean) {
      if (initial) setSourcesLoading(true);
      try {
        const [sourceData, jobData] = await Promise.all([
          api<{ sources: KnowledgeSource[] }>("/api/v1/sources", {
            token: session!.token,
            organizationId: session!.organizationId,
          }),
          api<{ jobs: IngestionJob[] }>("/api/v1/jobs?limit=50", {
            token: session!.token,
            organizationId: session!.organizationId,
          }).catch(() => ({ jobs: [] as IngestionJob[] })),
        ]);
        if (cancelled) return;
        setSources(sourceData.sources || []);
        setJobs(jobData.jobs || []);
      } catch {
        if (!cancelled) setSources([]);
      } finally {
        if (initial && !cancelled) setSourcesLoading(false);
      }
    }

    void refresh(true);
    const timer = window.setInterval(() => {
      const waitingSources = sourcesRef.current.some((source) => !source.document_count);
      const activeJobs = jobsRef.current.some(
        (job) => job.status === "pending" || job.status === "running",
      );
      if (waitingSources || activeJobs) void refresh(false);
    }, 3000);
    return () => {
      cancelled = true;
      window.clearInterval(timer);
    };
  }, [session]);

  useEffect(() => {
    if (!session || isNew) return;
    setLoading(true);
    api<Agent>(`/api/v1/agents/${id}`, {
      token: session.token,
      organizationId: session.organizationId,
    })
      .then((data) => {
        applyAgent(data);
        api<{
          score: number;
          items: { key: string; label: string; met: boolean; weight: number; detail: string }[];
        }>(`/api/v1/agents/${id}/readiness`, {
          token: session.token,
          organizationId: session.organizationId,
        })
          .then(setReadiness)
          .catch(() => setReadiness(null));
      })
      .catch((err) => setError(err instanceof Error ? err.message : "Error"))
      .finally(() => setLoading(false));
  }, [session, id, isNew]);

  useEffect(() => {
    if (!session) return;
    api<{ routes: { name: string; description: string }[] }>("/api/v1/gateway/routes", {
      token: session.token,
      organizationId: session.organizationId,
    })
      .then((out) => setRoutes(out.routes || []))
      .catch(() => setRoutes([]));
    api<{ entitlements: Record<string, boolean | number | null> }>("/api/v1/billing/entitlements", {
      token: session.token,
      organizationId: session.organizationId,
    })
      .then((out) => setCanCustomModel(out.entitlements?.custom_models === true))
      .catch(() => setCanCustomModel(false));
  }, [session]);

  useEffect(() => {
    if (!session || isNew || !id) return;
    void refreshVersions();
    void refreshDeployments();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [session, id, isNew]);

  useEffect(() => {
    const pending = (location.state as StudioLocationState | null)?.pendingMessage;
    if (!pending || isNew || !id) return;
    pendingRun.current = pending;
    setPlayInput(pending);
    navigate(location.pathname + location.search, { replace: true, state: {} });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [id, isNew]);

  useEffect(() => {
    if (!pendingRun.current || isNew || loading) return;
    const message = pendingRun.current;
    pendingRun.current = null;
    void runPlaygroundMessage(message);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [loading, isNew, id]);

  function applyAgent(data: Agent) {
    const next = {
      ...defaultConfig(),
      ...data.config,
      purpose: data.config?.purpose || "",
      source_ids: data.config?.source_ids ?? [],
    };
    const semanticOn = data.tools.includes("search_knowledge") || next.source_ids.length > 0;
    const sqlOn = data.tools.includes("query_database");
    const apiOn = data.tools.includes("call_api");
    const retrievalNext = {
      strategy: data.config?.retrieval?.strategy || "hybrid",
      top_k: data.config?.retrieval?.top_k ?? 10,
      score_threshold: data.config?.retrieval?.score_threshold ?? 0,
    };
    const outputNext = data.config?.output_schema ? JSON.stringify(data.config.output_schema, null, 2) : "";
    const workspaceNext = data.workspace_id || "";
    setName(data.name);
    setSystemPrompt(data.system_prompt || "");
    setModel(data.model || "zent-default");
    setConfig(next);
    setSemantic(semanticOn);
    setSql(sqlOn);
    setApiCalls(apiOn);
    const runtimeCfg = (next.runtime ?? null) as {
      tool_routing?: unknown;
      answer_gate?: unknown;
    } | null;
    setJevMode(
      runtimeCfg && typeof runtimeCfg.tool_routing === "boolean"
        ? runtimeCfg.tool_routing
          ? "on"
          : "off"
        : "inherit",
    );
    setAnswerGate(
      runtimeCfg && typeof runtimeCfg.answer_gate === "boolean"
        ? runtimeCfg.answer_gate
          ? "on"
          : "off"
        : "inherit",
    );
    setIsActive(data.is_active);
    setRetrieval(retrievalNext);
    setOutputSchema(outputNext);
    setWorkspaceId(workspaceNext);
    setSavedPayload(
      JSON.stringify(
        buildAgentPayload({
          name: data.name,
          systemPrompt: data.system_prompt || "",
          model: data.model || "zent-default",
          semantic: semanticOn,
          sql: sqlOn,
          apiCalls: apiOn,
          isActive: data.is_active,
          config: next,
          retrieval: retrievalNext,
          outputSchema: outputNext,
          workspaceId: workspaceNext,
        }),
      ),
    );
  }

  function goPanel(next: "configure" | "test") {
    const params = new URLSearchParams(searchParams);
    params.set("panel", next);
    setSearchParams(params, { replace: true });
  }

  function goAdvancedTab(next: AdvancedTab) {
    const params = new URLSearchParams(searchParams);
    params.set("panel", "advanced");
    params.set("tab", next);
    setSearchParams(params, { replace: true });
  }

  function toggleSource(sourceId: string) {
    const checked = config.source_ids.includes(sourceId);
    if (!checked && config.source_ids.length >= MAX_AGENT_SOURCES) {
      setError(AGENT_SOURCE_CAP_MSG);
      return;
    }
    const next = checked
      ? config.source_ids.filter((x) => x !== sourceId)
      : [...config.source_ids, sourceId];
    setConfig({ ...config, source_ids: next });
    if (next.length > 0) setSemantic(true);
  }

  function setSelectedSources(ids: string[]) {
    const next = ids.slice(0, MAX_AGENT_SOURCES);
    setConfig((prev) => ({ ...prev, source_ids: next }));
    if (next.length > 0) setSemantic(true);
    if (ids.length > MAX_AGENT_SOURCES) setError(AGENT_SOURCE_CAP_MSG);
  }

  function updateJevMode(mode: "inherit" | "on" | "off") {
    setJevMode(mode);
    updateRuntime({
      tool_routing: mode === "inherit" ? undefined : mode === "on",
      termination_gate: mode === "inherit" ? undefined : mode === "on",
    });
  }

  function updateAnswerGate(mode: "inherit" | "on" | "off") {
    setAnswerGate(mode);
    updateRuntime({ answer_gate: mode === "inherit" ? undefined : mode === "on" });
  }

  function updateRuntime(patch: Record<string, boolean | undefined>) {
    setConfig((prev) => {
      const current = {
        ...((prev.runtime ?? {}) as Record<string, boolean | undefined>),
      };
      for (const [key, value] of Object.entries(patch)) {
        if (value === undefined) delete current[key];
        else current[key] = value;
      }
      const hasValue = Object.values(current).some(
        (value) => typeof value === "boolean",
      );
      return {
        ...prev,
        runtime: hasValue ? (current as NonNullable<AgentConfig["runtime"]>) : undefined,
      };
    });
  }

  function enableAllTools() {
    setSemantic(true);
    setSql(hasDbSources(sourceTypesForSelection(sources, config.source_ids, sourcesLoading)));
    setApiCalls(true);
  }

  async function indexSource(sourceId: string) {
    if (!session) return;
    setIndexingId(sourceId);
    setError("");
    try {
      await api(`/api/v1/sources/${sourceId}/sync`, {
        method: "POST",
        token: session.token,
        organizationId: session.organizationId,
      });
      const jobData = await api<{ jobs: IngestionJob[] }>("/api/v1/jobs?limit=50", {
        token: session.token,
        organizationId: session.organizationId,
      }).catch(() => ({ jobs: [] as IngestionJob[] }));
      setJobs(jobData.jobs || []);
    } catch (err) {
      setError(err instanceof Error ? err.message : "No se pudo encolar el indexado");
    } finally {
      setIndexingId("");
    }
  }

  async function refreshVersions() {
    if (!session || isNew || !id) return;
    setVersionsLoading(true);
    try {
      const data = await api<{ versions: AgentVersion[] }>(`/api/v1/agents/${id}/versions`, {
        token: session.token,
        organizationId: session.organizationId,
      });
      setVersions(data.versions || []);
      if (!deployVersionId && data.versions?.length) setDeployVersionId(data.versions[0].id);
    } catch {
      setVersions([]);
    } finally {
      setVersionsLoading(false);
    }
  }

  async function refreshDeployments() {
    if (!session || isNew || !id) return;
    try {
      const [d, e] = await Promise.all([
        api<{ deployments: Deployment[] }>("/api/v1/deployments", {
          token: session.token,
          organizationId: session.organizationId,
        }),
        api<{ environments: Environment[] }>("/api/v1/environments", {
          token: session.token,
          organizationId: session.organizationId,
        }),
      ]);
      setDeployments((d.deployments || []).filter((x) => x.agent_id === id));
      setEnvironments(e.environments || []);
      if (!deployEnvId && e.environments?.length) setDeployEnvId(e.environments[0].id);
    } catch {
      setDeployments([]);
      setEnvironments([]);
    }
  }

  async function save(): Promise<Agent | null> {
    if (!session || !name.trim()) return null;
    if (config.source_ids.length > MAX_AGENT_SOURCES) {
      setError(AGENT_SOURCE_CAP_MSG);
      return null;
    }
    setSaving(true);
    setError("");
    setMsg("");
    try {
      if (isNew) {
        const created = await api<Agent>("/api/v1/agents", {
          method: "POST",
          token: session.token,
          organizationId: session.organizationId,
          body: JSON.stringify(payload),
        });
        setMsg("Agente creado.");
        return created;
      }
      const updated = await api<Agent>(`/api/v1/agents/${id}`, {
        method: "PUT",
        token: session.token,
        organizationId: session.organizationId,
        body: JSON.stringify(payload),
      });
      applyAgent(updated);
      setMsg("Cambios guardados.");
      return updated;
    } catch (err) {
      setError(err instanceof Error ? err.message : "Error al guardar");
      return null;
    } finally {
      setSaving(false);
    }
  }

  async function saveAndStay() {
    const saved = await save();
    if (saved && isNew) navigate(`/agents/${saved.id}`, { replace: true });
  }

  async function runPlayground(event: FormEvent) {
    event.preventDefault();
    await runPlaygroundMessage(playInput.trim());
  }

  async function runPlaygroundMessage(message: string) {
    if (!session || !message.trim()) return;
    if (isNew) {
      const created = await save();
      if (!created) return;
      navigate(`/agents/${created.id}?panel=test`, { replace: true, state: { pendingMessage: message } });
      return;
    }
    if (dirty) {
      const saved = await save();
      if (!saved) return;
    }
    if (!isActive) {
      setError("Actívalo para probar.");
      return;
    }
    setPlaying(true);
    setPlayStatus("Ejecutando agente…");
    setError("");
    setTurns((prev) => [...prev, { role: "user", text: message }]);
    setPlayInput("");
    try {
      const res = await fetch(`/api/v1/agents/${id}/run/stream`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          Authorization: `Bearer ${session.token}`,
          "X-Organization-Id": session.organizationId,
          "Idempotency-Key": crypto.randomUUID(),
        },
        body: JSON.stringify({ message }),
      });
      if (!res.ok || !res.body) {
        let detail = `HTTP ${res.status}`;
        try {
          const data = await res.json();
          detail = data.detail || data.message || detail;
        } catch {
          // keep HTTP status
        }
        throw new Error(typeof detail === "string" ? detail : "Error al ejecutar");
      }
      const reader = res.body.getReader();
      const decoder = new TextDecoder();
      let buffer = "";
      let answer = "";
      let used: string[] = [];
      let errors: string[] = [];
      let steps: unknown = [];
      let totalMs = 0;
      let model: string | null = null;
      let cost: number | null = null;
      let totalTokens: number | null = null;
      for (;;) {
        const { done, value } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });
        let idx: number;
        while ((idx = buffer.indexOf("\n\n")) !== -1) {
          const frame = buffer.slice(0, idx);
          buffer = buffer.slice(idx + 2);
          let eventName = "message";
          let data = "";
          for (const line of frame.split("\n")) {
            if (line.startsWith("event: ")) eventName = line.slice(7).trim();
            else if (line.startsWith("data: ")) data += line.slice(6);
          }
          if (!data) continue;
          const payloadJson = JSON.parse(data) as {
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
          if (eventName === "status") {
            setPlayStatus(payloadJson.phase === "running" ? "Ejecutando agente…" : "En curso…");
          } else if (eventName === "done") {
            answer = payloadJson.answer || "";
            used = sourceIdsFromSteps(payloadJson.steps);
            errors = toolErrorsFromSteps(payloadJson.steps);
            steps = payloadJson.steps;
            totalMs = payloadJson.total_latency_ms ?? 0;
            model = payloadJson.model ?? null;
            cost = typeof payloadJson.cost === "number" ? payloadJson.cost : null;
            totalTokens =
              typeof payloadJson.total_tokens === "number" ? payloadJson.total_tokens : null;
            setPlayStatus(payloadJson.status === "completed" ? "Listo" : payloadJson.status || "Listo");
          } else if (eventName === "error") {
            throw new Error(payloadJson.message || "Error en el stream");
          }
        }
      }
      setTurns((prev) => [
        ...prev,
        {
          role: "assistant",
          text: answer || "(sin respuesta)",
          sources: used,
          emptyHint: Boolean(config.source_ids.length) && used.length === 0 && errors.length === 0,
          error: errors[0],
          flow: flowFromAgentSteps(steps, totalMs, { model, cost, totalTokens }),
        },
      ]);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Error en playground");
      setPlayStatus("");
    } finally {
      setPlaying(false);
    }
  }

  async function createSnapshot() {
    if (!session || !id) return;
    setDeployBusy(true);
    setDeployError("");
    setDeployMsg("");
    try {
      await api(`/api/v1/agents/${id}/versions`, {
        method: "POST",
        token: session.token,
        organizationId: session.organizationId,
        body: JSON.stringify({}),
      });
      setDeployMsg("Snapshot creado (draft). Promuévelo a ready para desplegar.");
      await refreshVersions();
    } catch (err) {
      setDeployError(err instanceof Error ? err.message : "Error al crear snapshot");
    } finally {
      setDeployBusy(false);
    }
  }

  async function promoteVersion(versionId: string, status: string) {
    if (!session || !id) return;
    setDeployBusy(true);
    setDeployError("");
    setDeployMsg("");
    try {
      await api(`/api/v1/agents/${id}/versions/${versionId}/promote`, {
        method: "POST",
        token: session.token,
        organizationId: session.organizationId,
        body: JSON.stringify({ status }),
      });
      setDeployMsg("Versión promovida.");
      await refreshVersions();
    } catch (err) {
      setDeployError(err instanceof Error ? err.message : "Error al promover");
    } finally {
      setDeployBusy(false);
    }
  }

  async function deploy() {
    if (!session || !id || !deployVersionId || !deployEnvId) return;
    setDeployBusy(true);
    setDeployError("");
    setDeployMsg("");
    try {
      await api("/api/v1/deployments", {
        method: "POST",
        token: session.token,
        organizationId: session.organizationId,
        body: JSON.stringify({ agent_id: id, agent_version_id: deployVersionId, environment_id: deployEnvId }),
      });
      setDeployMsg("Deployment creado (healthy).");
      await refreshDeployments();
    } catch (err) {
      setDeployError(err instanceof Error ? err.message : "Error al desplegar");
    } finally {
      setDeployBusy(false);
    }
  }

  async function goLive() {
    if (!session || !id) return;
    const prodEnv = environments.find((e) => e.slug === "production");
    const candidate = versions.find((v) => v.status === "ready" || v.status === "staging" || v.status === "production");
    if (!prodEnv || !candidate) {
      setDeployError("Necesitas un entorno production y una versión lista.");
      return;
    }
    setDeployBusy(true);
    setDeployError("");
    setDeployMsg("");
    try {
      await api("/api/v1/deployments", {
        method: "POST",
        token: session.token,
        organizationId: session.organizationId,
        body: JSON.stringify({ agent_id: id, agent_version_id: candidate.id, environment_id: prodEnv.id }),
      });
      setDeployMsg(`v${candidate.version_number} desplegada en production.`);
      await refreshDeployments();
    } catch (err) {
      setDeployError(err instanceof Error ? err.message : "Error al desplegar");
    } finally {
      setDeployBusy(false);
    }
  }

  async function rollback(deploymentId: string) {
    if (!session || !id) return;
    setDeployBusy(true);
    setDeployError("");
    setDeployMsg("");
    try {
      await api(`/api/v1/deployments/${deploymentId}/rollback`, {
        method: "POST",
        token: session.token,
        organizationId: session.organizationId,
      });
      setDeployMsg("Rollback ejecutado.");
      await refreshDeployments();
    } catch (err) {
      setDeployError(err instanceof Error ? err.message : "Error en rollback");
    } finally {
      setDeployBusy(false);
    }
  }

  async function loadEvents(deploymentId: string) {
    if (!session) return;
    try {
      const data = await api<{ events: { event: string; created_at: string | null; metadata: Record<string, unknown> }[] }>(
        `/api/v1/deployments/${deploymentId}/events`,
        { token: session.token, organizationId: session.organizationId },
      );
      setEventsFor({ deploymentId, events: data.events || [] });
    } catch {
      setEventsFor(null);
    }
  }

  if (loading) {
    return (
      <Panel className="p-4">
        <SkeletonBlock rows={6} />
      </Panel>
    );
  }

  const configureVisible = panel !== "test";
  const testVisible = panel !== "configure";
  const saveState: SaveState = saving ? "saving" : dirty ? "dirty" : "idle";
  const agentSourceTypes = sourceTypesForSelection(sources, config.source_ids, sourcesLoading);

  return (
    <div>
      <Breadcrumb
        items={[
          { label: "Agentes", to: "/agents" },
          { label: isNew ? "Nuevo agente" : name || "Agente" },
        ]}
      />
      <div className="sticky top-0 z-20 mb-4 border-b border-border bg-bg py-3">
        <PageHeader
          className="mb-0"
          title={isNew ? "Nuevo agente" : name || "Agente"}
          subtitle="Dile qué hace, elige fuentes y pruébalo. Siempre puedes volver a editar."
          meta={<SaveStatus state={saveState} dirtyLabel="Cambios sin guardar" />}
          actions={
            <div className="flex flex-wrap items-center gap-2">
              {!isNew && (
                <Switch
                  checked={isActive}
                  onCheckedChange={setIsActive}
                  label="Activo"
                  className="w-auto items-center gap-2 rounded-md border border-border bg-raised px-3 py-2"
                />
              )}
              {!isNew && id && (
                <Link to={`/chat?target=agent&id=${id}`} className="btn btn-ghost">
                  <ChatCircleDots size={16} aria-hidden />
                  Probar en Playground
                </Link>
              )}
              <Button
                variant="primary"
                leadingIcon={FloppyDisk}
                loading={saving}
                disabled={!name.trim()}
                onClick={() => void saveAndStay()}
              >
                {isNew ? "Crear agente" : "Guardar"}
              </Button>
              <Button
                variant="ghost"
                leadingIcon={ArrowLeft}
                onClick={() => {
                  if (dirty) {
                    setLeaveOpen(true);
                    return;
                  }
                  navigate("/agents");
                }}
              >
                Volver
              </Button>
            </div>
          }
        />
      </div>
      <ErrorInline message={error} />
      <SuccessInline message={msg} />

      <div className="tabs mb-4 lg:hidden" role="tablist" aria-label="Estudio">
        <button
          type="button"
          role="tab"
          aria-selected={panel !== "test"}
          className="tab"
          onClick={() => goPanel("configure")}
        >
          Configurar
        </button>
        <button
          type="button"
          role="tab"
          aria-selected={panel === "test"}
          className="tab"
          onClick={() => goPanel("test")}
        >
          Probar
        </button>
      </div>

      <div className="grid gap-4 lg:grid-cols-[minmax(0,22rem)_minmax(0,1fr)] xl:grid-cols-[minmax(0,26rem)_minmax(0,1fr)]">
        <Panel className={configureVisible ? "" : "hidden lg:block"}>
          <PanelHeader
            title="Contexto"
            description="Qué hace este agente y con qué material responde."
          />
          <div className="grid gap-5 p-4">
            <AgentPurposeForm
              name={name}
              purpose={config.purpose || ""}
              instructions={systemPrompt}
              nameError={nameTouched && !name.trim() ? "Necesitas un nombre para guardar." : undefined}
              onName={(value) => {
                setNameTouched(true);
                setName(value);
              }}
              onPurpose={(value) => setConfig({ ...config, purpose: value })}
              onInstructions={setSystemPrompt}
            />
            <div className="border-t border-border pt-4">
              <AgentSourcePicker
                sources={sources}
                selectedIds={config.source_ids}
                jobs={jobs}
                loading={sourcesLoading}
                indexingId={indexingId}
                onToggle={toggleSource}
                onSetSelected={setSelectedSources}
                onIndex={(sourceId) => void indexSource(sourceId)}
              />
            </div>
          </div>
        </Panel>
        <div className={testVisible ? "" : "hidden lg:block"}>
          <AgentTestChat
            turns={turns}
            input={playInput}
            status={playStatus}
            playing={playing}
            inactive={!isNew && !isActive}
            sources={sources}
            selectedIds={config.source_ids}
            onInput={setPlayInput}
            onSubmit={(e) => void runPlayground(e)}
            onActivate={() => setIsActive(true)}
            session={session}
          />
        </div>
      </div>

      <AgentAdvancedPanel
        tab={advancedTab}
        onTab={goAdvancedTab}
        open={advancedOpen}
        onToggle={(next) => {
          if (next === advancedOpen) return;
          const params = new URLSearchParams(searchParams);
          if (next) params.set("panel", "advanced");
          else if (params.get("panel") === "advanced") params.delete("panel");
          setSearchParams(params, { replace: true });
        }}
        isNew={isNew}
        id={isNew ? undefined : id}
        session={session}
        model={model}
        setModel={setModel}
        routes={routes}
        canCustomModel={canCustomModel}
        config={config}
        setConfig={setConfig}
        semantic={semantic}
        setSemantic={setSemantic}
        sql={sql}
        setSql={setSql}
        apiCalls={apiCalls}
        setApiCalls={setApiCalls}
        retrieval={retrieval}
        setRetrieval={setRetrieval}
        jevMode={jevMode}
        setJevMode={updateJevMode}
        answerGate={answerGate}
        setAnswerGate={updateAnswerGate}
        sourceTypes={agentSourceTypes}
        onEnableAll={enableAllTools}
        outputSchema={outputSchema}
        setOutputSchema={setOutputSchema}
        readiness={readiness}
        versions={versions}
        versionsLoading={versionsLoading}
        deployments={deployments}
        environments={environments}
        deployVersionId={deployVersionId}
        setDeployVersionId={setDeployVersionId}
        deployEnvId={deployEnvId}
        setDeployEnvId={setDeployEnvId}
        deployBusy={deployBusy}
        deployMsg={deployMsg}
        deployError={deployError}
        eventsFor={eventsFor}
        embedOrigins={embedOrigins}
        setEmbedOrigins={setEmbedOrigins}
        embedToken={embedToken}
        embedScript={embedScript}
        embedBusy={embedBusy}
        onCreateSnapshot={() => void createSnapshot()}
        onPromote={(versionId, status) => void promoteVersion(versionId, status)}
        onDeploy={() => void deploy()}
        onGoLive={() => void goLive()}
        onRollback={(deploymentId) => void rollback(deploymentId)}
        onLoadEvents={(deploymentId) => void loadEvents(deploymentId)}
        onCreateEmbed={() => {
          if (!session || !id) return;
          setEmbedBusy(true);
          setError("");
          api<{ token: string; public_id: string }>(`/api/v1/agents/${id}/embed/token`, {
            method: "POST",
            token: session.token,
            organizationId: session.organizationId,
            body: JSON.stringify({
              allowed_origins: embedOrigins
                .split(",")
                .map((s) => s.trim())
                .filter(Boolean),
            }),
          })
            .then((data) => {
              setEmbedToken(data.token);
              setEmbedScript(`<script src="${window.location.origin}/embed.js" data-embed="${data.public_id}"></script>`);
              setMsg("Token creado. Cópialo ahora; no se vuelve a mostrar.");
            })
            .catch((err) => setError(err instanceof Error ? err.message : "Error embed"))
            .finally(() => setEmbedBusy(false));
        }}
        onRevokeEmbed={() => {
          if (!session || !id) return;
          setEmbedBusy(true);
          api(`/api/v1/agents/${id}/embed/revoke`, {
            method: "POST",
            token: session.token,
            organizationId: session.organizationId,
          })
            .then(() => {
              setEmbedToken("");
              setEmbedScript("");
              setMsg("Token revocado.");
            })
            .catch((err) => setError(err instanceof Error ? err.message : "Error"))
            .finally(() => setEmbedBusy(false));
        }}
      />

      <ConfirmDialog
        open={leaveOpen}
        onOpenChange={setLeaveOpen}
        title="Salir sin guardar"
        body="Hay cambios sin guardar en este agente. Si sales ahora, se pierden."
        confirmLabel="Salir sin guardar"
        cancelLabel="Seguir editando"
        onConfirm={() => {
          setLeaveOpen(false);
          navigate("/agents");
        }}
      />
    </div>
  );
}
