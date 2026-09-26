// =============================================================================
// useAgentStudio — estado y acciones del Agent Studio.
// =============================================================================
// Una sola fuente de verdad por dato: el estado local es exactamente lo que se
// serializa en `buildAgentPayload`. Nada de espejos (nada de `jevMode` aparte de
// `config.runtime`) para que la UI no pueda mostrar algo distinto de lo guardado.
// =============================================================================
import { FormEvent, useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useLocation, useNavigate, useParams, useSearchParams } from "react-router-dom";
import { api } from "../../api";
import { useAuth } from "../../auth";
import { flowFromAgentStepsLegacy } from "../../pages/chat/runPlaygroundTurn";
import {
  CUSTOM_PROFILE,
  DEFAULT_MODEL_ROUTE,
  RECOMMENDED_LIMITS,
  RECOMMENDED_RETRIEVAL,
  capabilityLabels,
  matchResponsePreset,
  recommendAgentConfiguration,
  type AgentRecommendation,
  type CapabilityFlags,
} from "./agentModes";
import { AGENT_SOURCE_CAP_MSG, MAX_AGENT_SOURCES } from "./AgentSourcePicker";
import type { ChatTurn } from "./AgentTestChat";
import { hasDbSources, sourceTypesForSelection } from "./toolApplicability";
import {
  DEFAULT_RESPONSE_PROFILE,
  RESPONSE_PROFILE_PRESETS,
  buildAgentPayload,
  defaultConfig,
  resolveStudioView,
  sourceIdsFromSteps,
  toolErrorsFromSteps,
  type AdvancedGroup,
  type Agent,
  type AgentConfig,
  type AgentStage,
  type AgentVersion,
  type Deployment,
  type Environment,
  type IngestionJob,
  type KnowledgeSource,
  type ResponseProfile,
} from "./types";

type Readiness = {
  score: number;
  items: { key: string; label: string; met: boolean; weight: number; detail: string }[];
};

type DeploymentEvents = {
  deploymentId: string;
  events: { event: string; created_at: string | null; metadata: Record<string, unknown> }[];
};

type StudioLocationState = { pendingMessage?: string };

export type AgentStudioModel = ReturnType<typeof useAgentStudio>;

export function useAgentStudio() {
  const { id } = useParams<{ id: string }>();
  const isNew = !id || id === "new";
  const navigate = useNavigate();
  const location = useLocation();
  const [searchParams, setSearchParams] = useSearchParams();
  const { session } = useAuth();

  const view = resolveStudioView(searchParams.get("panel"), searchParams.get("tab"));
  const { stage, advancedOpen, advancedGroup, publishFocus } = view;

  const [sources, setSources] = useState<KnowledgeSource[]>([]);
  const [jobs, setJobs] = useState<IngestionJob[]>([]);
  const [sourcesLoading, setSourcesLoading] = useState(true);
  const [indexingId, setIndexingId] = useState("");
  const [name, setName] = useState("");
  const [systemPrompt, setSystemPrompt] = useState("");
  const [model, setModel] = useState(DEFAULT_MODEL_ROUTE);
  const [routes, setRoutes] = useState<{ name: string; description: string }[]>([]);
  const [canCustomModel, setCanCustomModel] = useState(false);
  const [config, setConfig] = useState(defaultConfig());
  const [semantic, setSemantic] = useState(true);
  const [sql, setSql] = useState(true);
  const [apiCalls, setApiCalls] = useState(true);
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
  const [eventsFor, setEventsFor] = useState<DeploymentEvents | null>(null);
  const [retrieval, setRetrieval] = useState({ ...RECOMMENDED_RETRIEVAL });
  const [outputSchema, setOutputSchema] = useState("");
  const [readiness, setReadiness] = useState<Readiness | null>(null);
  const [workspaceId, setWorkspaceId] = useState("");
  const [savedPayload, setSavedPayload] = useState("");
  const [nameTouched, setNameTouched] = useState(false);
  const [leaveOpen, setLeaveOpen] = useState(false);
  /** Detalle del perfil de respuesta en el panel (Nivel 2). Estado de UI puro. */
  const [profileCustomOpen, setProfileCustomOpen] = useState(false);
  /** Panel de recomendación automática: sólo visible cuando el usuario lo pide. */
  const [aiSuggestionOpen, setAiSuggestionOpen] = useState(false);
  const [aiBusy, setAiBusy] = useState(false);
  const [aiError, setAiError] = useState("");
  const [aiNotice, setAiNotice] = useState("");
  const pendingRun = useRef<string | null>(null);

  const profile = useMemo<ResponseProfile>(
    () => ({ ...DEFAULT_RESPONSE_PROFILE, ...(config.response_profile ?? {}) }),
    [config.response_profile],
  );
  const capabilities = useMemo<CapabilityFlags>(
    () => ({ knowledge: semantic, data: sql, integrations: apiCalls }),
    [semantic, sql, apiCalls],
  );
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
      strategy: data.config?.retrieval?.strategy || RECOMMENDED_RETRIEVAL.strategy,
      top_k: data.config?.retrieval?.top_k ?? RECOMMENDED_RETRIEVAL.top_k,
      score_threshold: data.config?.retrieval?.score_threshold ?? RECOMMENDED_RETRIEVAL.score_threshold,
    };
    const outputNext = data.config?.output_schema ? JSON.stringify(data.config.output_schema, null, 2) : "";
    const workspaceNext = data.workspace_id || "";
    setName(data.name);
    setSystemPrompt(data.system_prompt || "");
    setModel(data.model || DEFAULT_MODEL_ROUTE);
    setConfig(next);
    setSemantic(semanticOn);
    setSql(sqlOn);
    setApiCalls(apiOn);
    setIsActive(data.is_active);
    setRetrieval(retrievalNext);
    setOutputSchema(outputNext);
    setWorkspaceId(workspaceNext);
    setSavedPayload(
      JSON.stringify(
        buildAgentPayload({
          name: data.name,
          systemPrompt: data.system_prompt || "",
          model: data.model || DEFAULT_MODEL_ROUTE,
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

  useEffect(() => {
    if (!session || isNew) return;
    setLoading(true);
    api<Agent>(`/api/v1/agents/${id}`, {
      token: session.token,
      organizationId: session.organizationId,
    })
      .then((data) => {
        applyAgent(data);
        api<Readiness>(`/api/v1/agents/${id}/readiness`, {
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

  // ---------------------------------------------------------------------------
  // Navegación entre etapas
  // ---------------------------------------------------------------------------

  const goStage = useCallback(
    (next: AgentStage) => {
      const params = new URLSearchParams(searchParams);
      params.set("panel", next);
      params.delete("tab");
      setSearchParams(params, { replace: true });
    },
    [searchParams, setSearchParams],
  );

  const goAdvancedGroup = useCallback(
    (group: AdvancedGroup | null) => {
      const params = new URLSearchParams(searchParams);
      params.set("panel", "develop");
      if (group) params.set("tab", group);
      else params.delete("tab");
      setSearchParams(params, { replace: true });
    },
    [searchParams, setSearchParams],
  );

  // ---------------------------------------------------------------------------
  // Configuración
  // ---------------------------------------------------------------------------

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

  function toggleCapability(capability: keyof CapabilityFlags, value: boolean) {
    if (capability === "knowledge") setSemantic(value);
    else if (capability === "data") setSql(value);
    else setApiCalls(value);
  }

  function enableAvailableCapabilities() {
    const dbAvailable = hasDbSources(sourceTypes);
    setSemantic(true);
    setApiCalls(true);
    setSql(dbAvailable);
  }

  function updateRuntime(patch: {
    tool_routing?: boolean | null;
    termination_gate?: boolean | null;
    answer_gate?: boolean | null;
  }) {
    setConfig((prev) => {
      const current = { ...((prev.runtime ?? {}) as Record<string, unknown>) };
      for (const [key, value] of Object.entries(patch)) {
        if (value === null || value === undefined) delete current[key];
        else current[key] = value;
      }
      const hasValue = Object.values(current).some(
        (value) => typeof value === "boolean" || typeof value === "string",
      );
      return {
        ...prev,
        runtime: hasValue ? (current as NonNullable<AgentConfig["runtime"]>) : undefined,
      };
    });
  }

  function applyResponseProfile(next: ResponseProfile) {
    setConfig((prev) => ({ ...prev, response_profile: { ...next, preset: next.preset } }));
  }

  function applyPreset(presetId: string) {
    const preset = PRESET_LOOKUP(presetId);
    if (!preset) return;
    setConfig((prev) => ({
      ...prev,
      response_profile: { ...DEFAULT_RESPONSE_PROFILE, ...preset.profile, preset: preset.id },
    }));
  }

  function restoreRetrievalRecommended() {
    setRetrieval({ ...RECOMMENDED_RETRIEVAL });
  }

  function restoreLimitsRecommended() {
    setConfig((prev) => ({ ...prev, limits: { ...RECOMMENDED_LIMITS } }));
  }

  // ---------------------------------------------------------------------------
  // Recomendación automática
  // ---------------------------------------------------------------------------

  const sourceTypes = sourceTypesForSelection(sources, config.source_ids, sourcesLoading);
  const selectedSources = useMemo(
    () => sources.filter((source) => config.source_ids.includes(source.id)),
    [sources, config.source_ids],
  );
  const recommendation: AgentRecommendation = useMemo(
    () =>
      recommendAgentConfiguration({
        purpose: config.purpose || "",
        sourceTypes,
        sourceKindLabels: selectedSources.map((source) => source.type),
      }),
    [config.purpose, sourceTypes, selectedSources],
  );
  const profilePresetId = useMemo(() => matchResponsePreset(config.response_profile), [config.response_profile]);
  const isProfileCustom = profilePresetId === CUSTOM_PROFILE;

  function applyRecommendation() {
    setModel(recommendation.model);
    applyPreset(recommendation.presetId);
    setSemantic(recommendation.capabilities.knowledge);
    setSql(recommendation.capabilities.data);
    setApiCalls(recommendation.capabilities.integrations);
    setAiNotice("Configuración aplicada. Guardá para conservarla.");
  }

  /**
   * Borrador de estilo con IA. Usa el endpoint existente, que sólo lee datos
   * reales del agente y rechaza mencionar capacidades no configuradas.
   */
  async function requestProfileDraft() {
    if (!session || isNew || !id) {
      setAiNotice("");
      setAiError("Guardá el agente primero: el generador sólo usa datos reales del agente.");
      return;
    }
    setAiBusy(true);
    setAiError("");
    setAiNotice("");
    try {
      const data = await api<{ draft: Record<string, unknown> }>(
        `/api/v1/agents/${id}/config/response-profile`,
        { method: "POST", token: session.token, organizationId: session.organizationId, body: JSON.stringify({}) },
      );
      const draft = data.draft as Partial<ResponseProfile>;
      setConfig((prev) => {
        const current = { ...DEFAULT_RESPONSE_PROFILE, ...(prev.response_profile ?? {}) };
        return {
          ...prev,
          response_profile: {
            ...current,
            ...draft,
            preset: typeof draft.preset === "string" ? draft.preset : current.preset,
          } as ResponseProfile,
        };
      });
      setAiNotice("Perfil propuesto a partir de datos reales del agente. Revisalo antes de guardar.");
    } catch (err) {
      setAiError(err instanceof Error ? err.message : "No se pudo generar el borrador");
    } finally {
      setAiBusy(false);
    }
  }

  // ---------------------------------------------------------------------------
  // Fuentes y datos remotos
  // ---------------------------------------------------------------------------

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
      setDeployVersionId((current) => current || data.versions?.[0]?.id || "");
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
      setDeployEnvId((current) => current || e.environments?.[0]?.id || "");
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
      const warnings = (updated as { warnings?: string[] }).warnings;
      setMsg(warnings?.length ? `Cambios guardados. ${warnings.join(" ")}` : "Cambios guardados.");
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
      let runId: string | null = null;
      let backendFlow: Record<string, unknown> | null = null;
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
            run_id?: string;
            flow?: Record<string, unknown> | null;
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
            totalTokens = typeof payloadJson.total_tokens === "number" ? payloadJson.total_tokens : null;
            runId = payloadJson.run_id ?? null;
            // El backend manda el flow canónico: el portal no lo reconstruye.
            backendFlow =
              payloadJson.flow && typeof payloadJson.flow === "object" ? payloadJson.flow : null;
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
          runId: runId ?? undefined,
          question: message,
          flow: backendFlow ?? flowFromAgentStepsLegacy(steps, totalMs, { model, cost, totalTokens }),
        },
      ]);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Error en playground");
      setPlayStatus("");
    } finally {
      setPlaying(false);
    }
  }

  // ---------------------------------------------------------------------------
  // Publicación
  // ---------------------------------------------------------------------------

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
      setDeployMsg("Versión creada (draft). Promovéla a lista para desplegar.");
      await refreshVersions();
    } catch (err) {
      setDeployError(err instanceof Error ? err.message : "Error al crear la versión");
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
      setDeployMsg("Publicación creada (healthy).");
      await refreshDeployments();
    } catch (err) {
      setDeployError(err instanceof Error ? err.message : "Error al publicar");
    } finally {
      setDeployBusy(false);
    }
  }

  async function goLive() {
    if (!session || !id) return;
    const prodEnv = environments.find((e) => e.slug === "production");
    const candidate = versions.find(
      (v) => v.status === "ready" || v.status === "staging" || v.status === "production",
    );
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
      setDeployMsg(`v${candidate.version_number} publicada en production.`);
      await refreshDeployments();
    } catch (err) {
      setDeployError(err instanceof Error ? err.message : "Error al publicar");
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
      const data = await api<{ events: DeploymentEvents["events"] }>(
        `/api/v1/deployments/${deploymentId}/events`,
        { token: session.token, organizationId: session.organizationId },
      );
      setEventsFor({ deploymentId, events: data.events || [] });
    } catch {
      setEventsFor(null);
    }
  }

  async function createEmbed() {
    if (!session || !id) return;
    setEmbedBusy(true);
    setError("");
    try {
      const data = await api<{ token: string; public_id: string }>(`/api/v1/agents/${id}/embed/token`, {
        method: "POST",
        token: session.token,
        organizationId: session.organizationId,
        body: JSON.stringify({
          allowed_origins: embedOrigins
            .split(",")
            .map((s) => s.trim())
            .filter(Boolean),
        }),
      });
      setEmbedToken(data.token);
      setEmbedScript(`<script src="${window.location.origin}/embed.js" data-embed="${data.public_id}"></script>`);
      setMsg("Token creado. Cópialo ahora; no se vuelve a mostrar.");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Error embed");
    } finally {
      setEmbedBusy(false);
    }
  }

  async function revokeEmbed() {
    if (!session || !id) return;
    setEmbedBusy(true);
    try {
      await api(`/api/v1/agents/${id}/embed/revoke`, {
        method: "POST",
        token: session.token,
        organizationId: session.organizationId,
      });
      setEmbedToken("");
      setEmbedScript("");
      setMsg("Token revocado.");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Error");
    } finally {
      setEmbedBusy(false);
    }
  }

  return {
    // contexto
    id,
    isNew,
    session,
    stage,
    publishFocus,
    advancedOpen,
    advancedGroup,
    goStage,
    goAdvancedGroup,
    // identidad
    name,
    setName: (value: string) => {
      setNameTouched(true);
      setName(value);
    },
    nameTouched,
    systemPrompt,
    setSystemPrompt,
    // estado
    config,
    setConfig,
    profile,
    applyResponseProfile,
    applyPreset,
    profilePresetId,
    isProfileCustom,
    profileCustomOpen,
    setProfileCustomOpen,
    aiSuggestionOpen,
    openAiSuggestion: () => {
      setAiSuggestionOpen(true);
      setAiError("");
      setAiNotice("");
    },
    dismissAiSuggestion: () => setAiSuggestionOpen(false),
    aiBusy,
    aiError,
    aiNotice,
    requestProfileDraft,
    capabilities,
    toggleCapability,
    enableAvailableCapabilities,
    updateRuntime,
    retrieval,
    setRetrieval,
    restoreRetrievalRecommended,
    restoreLimitsRecommended,
    outputSchema,
    setOutputSchema,
    model,
    setModel,
    routes,
    canCustomModel,
    isActive,
    setIsActive,
    workspaceId,
    // fuentes
    sources,
    selectedSources,
    sourcesLoading,
    sourceTypes,
    jobs,
    indexingId,
    toggleSource,
    setSelectedSources,
    indexSource,
    // recomendación
    recommendation,
    applyRecommendation,
    capabilityLabels: capabilityLabels(capabilities),
    // guardado
    loading,
    saving,
    dirty,
    error,
    msg,
    readiness,
    leaveOpen,
    setLeaveOpen,
    save,
    saveAndStay,
    // playground
    turns,
    playInput,
    setPlayInput,
    playStatus,
    playing,
    runPlayground,
    runPlaygroundMessage,
    clearPlayground: () => {
      setTurns([]);
      setPlayStatus("");
    },
    // publicación
    versions,
    versionsLoading,
    deployments,
    environments,
    deployVersionId,
    setDeployVersionId,
    deployEnvId,
    setDeployEnvId,
    deployBusy,
    deployMsg,
    deployError,
    eventsFor,
    createSnapshot,
    promoteVersion,
    deploy,
    goLive,
    rollback,
    loadEvents,
    embedOrigins,
    setEmbedOrigins,
    embedToken,
    embedScript,
    embedBusy,
    createEmbed,
    revokeEmbed,
  };
}

function PRESET_LOOKUP(presetId: string) {
  return RESPONSE_PROFILE_PRESETS.find((preset) => preset.id === presetId) ?? null;
}
