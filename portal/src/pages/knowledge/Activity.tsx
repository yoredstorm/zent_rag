// =============================================================================
// Actividad — el aprendizaje en lenguaje humano (y los runs en modo técnico)
// =============================================================================
import { ArrowsClockwise, Lightning, Plus } from "@phosphor-icons/react";
import { useCallback, useEffect, useMemo, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { api } from "../../api";
import { useAuth } from "../../auth";
import {
  Badge,
  Button,
  ButtonLink,
  cn,
  EmptyState,
  ErrorInline,
  Panel,
  PanelHeader,
  PageHeader,
  Select,
  Skeleton,
} from "../../components/ui";
import { KnowledgeLayout } from "../../components/KnowledgeLayout";
import { ActivityFeed } from "../../components/knowledge/ActivityFeed";
import { KnowledgeDelta } from "../../components/knowledge/KnowledgeDelta";
import { LearningActivityFeed } from "../../components/knowledgeLearning/LearningActivityFeed";
import { LearningProgress } from "../../components/knowledgeLearning/LearningProgress";
import { LearningStageTimeline } from "../../components/knowledgeLearning/LearningStageTimeline";
import { KNOWLEDGE_HEADINGS } from "../../lib/knowledgeNav";
import {
  cancelLearning,
  fetchLearningRun,
  fetchLearningRuns,
  fetchLearningSources,
  stageLabel,
  streamRunEvents,
  type LearningEvent,
  type LearningRun,
  type SourceLearning,
} from "../../lib/knowledgeLearning";
import {
  fetchKnowledgeCompilations,
  learnSource,
  type KnowledgeCompilation,
} from "../../lib/knowledgeModel";
import {
  fetchKnowledgeFeed,
  type KnowledgeFeedItem,
} from "../../lib/knowledgeActivity";
import { fmtDateTime } from "../../lib/format";

type ConnectorRow = {
  id: string;
  name: string;
  type: string;
  config?: Record<string, unknown> | null;
};

const ACTIVE_STATUSES = new Set(["queued", "running", "awaiting_validation"]);

const FEED_FILTERS = [
  { id: "all", label: "Todo" },
  { id: "discovery", label: "Descubrimiento" },
  { id: "ai", label: "Comprensión" },
  { id: "validation", label: "Validación" },
  { id: "indexing", label: "Organización" },
  { id: "system", label: "Sistema" },
];

function runTone(status: string): "ok" | "danger" | "warn" | "info" | "neutral" {
  if (status === "completed") return "ok";
  if (status === "failed") return "danger";
  if (status === "cancelled") return "neutral";
  if (status === "awaiting_validation") return "warn";
  return "info";
}

function FeedView() {
  const [items, setItems] = useState<KnowledgeFeedItem[]>([]);
  const [filter, setFilter] = useState("all");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  const load = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      setItems(await fetchKnowledgeFeed(100));
    } catch (err) {
      setItems([]);
      setError(
        err instanceof Error ? err.message : "No pudimos cargar la actividad."
      );
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const filtered = useMemo(
    () =>
      filter === "all"
        ? items
        : items.filter((item) => item.category === filter),
    [items, filter]
  );

  return (
    <div className="flex flex-col gap-4">
      <KnowledgeDelta initialWindow="7d" />

      <Panel className="overflow-hidden">
        <div className="panel-header flex-col items-start gap-3 sm:flex-row sm:items-center">
          <div className="min-w-0">
            <h2 className="text-h3">Aprendizaje reciente</h2>
            <p className="mt-0.5 text-xs text-muted">
              Cada descubrimiento, comprensión y conexión real. Los eventos
              repetidos se agrupan.
            </p>
          </div>
          <div className="flex flex-wrap gap-1.5">
            {FEED_FILTERS.map((option) => (
              <button
                key={option.id}
                type="button"
                className={cn("kh-window-tab", filter === option.id && "is-active")}
                aria-pressed={filter === option.id}
                onClick={() => setFilter(option.id)}
              >
                {option.label}
              </button>
            ))}
          </div>
        </div>
        <div className="panel-body">
          <ErrorInline message={error} className="mb-3" />
          {loading ? (
            <div className="flex flex-col gap-3" aria-busy="true">
              {[0, 1, 2, 3, 4, 5].map((i) => (
                <Skeleton key={i} className="h-10 rounded-sm" />
              ))}
            </div>
          ) : filtered.length === 0 ? (
            <EmptyState
              icon={Lightning}
              title="Sin actividad en este filtro"
              body="Cuando ZENT aprenda de una fuente, cada descubrimiento aparecerá aquí con su evento real."
              action={
                <ButtonLink to="/knowledge/sources?new=1" variant="primary" leadingIcon={Plus}>
                  Añadir fuente
                </ButtonLink>
              }
            />
          ) : (
            <ActivityFeed
              items={filtered}
              loading={false}
              initialLimit={filtered.length}
              expandable={false}
              bare
            />
          )}
        </div>
      </Panel>
    </div>
  );
}

function RunsView() {
  const { session } = useAuth();
  const [params, setParams] = useSearchParams();
  const runId = params.get("run");

  const [runs, setRuns] = useState<LearningRun[]>([]);
  const [sources, setSources] = useState<SourceLearning[]>([]);
  const [connectorNames, setConnectorNames] = useState<Record<string, string>>({});
  const [connectorConfigs, setConnectorConfigs] = useState<
    Record<string, Record<string, unknown>>
  >({});
  const [selectedSource, setSelectedSource] = useState("");
  const [run, setRun] = useState<LearningRun | null>(null);
  const [compilations, setCompilations] = useState<KnowledgeCompilation[]>([]);
  const [liveEvents, setLiveEvents] = useState<LearningEvent[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [actionMessage, setActionMessage] = useState("");
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    if (!session) return;
    setLoading(true);
    setError("");
    try {
      const sourcesData = await fetchLearningSources();
      setSources(sourcesData);
      try {
        const connectorsData = await api<{ connectors: ConnectorRow[] }>(
          "/api/v1/connectors",
          { token: session.token, organizationId: session.organizationId }
        );
        setConnectorNames(
          Object.fromEntries(
            (connectorsData.connectors ?? []).map((row) => [row.id, row.name])
          )
        );
        setConnectorConfigs(
          Object.fromEntries(
            (connectorsData.connectors ?? [])
              .filter((row) => row.config && typeof row.config === "object")
              .map((row) => [row.id, row.config as Record<string, unknown>])
          )
        );
      } catch {
        // Sin permiso de conectores: la etiqueta cae al engine/id.
      }
      const runsData = await fetchLearningRuns({ limit: 30 });
      setRuns(runsData.runs);
      try {
        const compiled = await fetchKnowledgeCompilations(20);
        setCompilations(compiled.items);
      } catch {
        setCompilations([]);
      }
    } catch (err) {
      setRuns([]);
      setError(
        err instanceof Error ? err.message : "No pudimos cargar la actividad técnica."
      );
    } finally {
      setLoading(false);
    }
  }, [session]);

  const sourceLabel = useCallback(
    (source: SourceLearning) =>
      connectorNames[source.connector_id] ||
      source.engine ||
      `Fuente ${source.source_id.slice(0, 8)}`,
    [connectorNames]
  );

  const isLearnable = useCallback(
    (source: SourceLearning) => {
      const config = connectorConfigs[source.connector_id];
      if (!config) return true;
      const host = String(config.host ?? "");
      return !config.session_id && host !== "file-virtual";
    },
    [connectorConfigs]
  );

  const learnableSources = useMemo(
    () => sources.filter(isLearnable),
    [sources, isLearnable]
  );

  useEffect(() => {
    if (selectedSource && learnableSources.some((s) => s.source_id === selectedSource)) {
      return;
    }
    setSelectedSource(learnableSources[0]?.source_id ?? "");
  }, [learnableSources, selectedSource]);

  useEffect(() => {
    void load();
    // Solo al montar / cambiar de sesión.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [session]);

  const activeRunId = useMemo(() => {
    if (runId) return runId;
    const active = runs.find((item) => ACTIVE_STATUSES.has(item.status));
    return active?.id ?? runs[0]?.id ?? null;
  }, [runId, runs]);

  const loadRun = useCallback(async (id: string) => {
    try {
      setRun(await fetchLearningRun(id));
    } catch (err) {
      setRun(null);
      setError(err instanceof Error ? err.message : "No pudimos cargar el run.");
    }
  }, []);

  useEffect(() => {
    if (activeRunId) void loadRun(activeRunId);
    else setRun(null);
  }, [activeRunId, loadRun]);

  const streamRunId = run && ACTIVE_STATUSES.has(run.status) ? run.id : null;

  useEffect(() => {
    setLiveEvents([]);
    if (!streamRunId) return;
    const handle = streamRunEvents({
      runId: streamRunId,
      sinceSeq: 0,
      onEvent: (event) => setLiveEvents((prev) => [...prev, event]),
      onError: () => setError("Se perdió la conexión en vivo; reintenta recargando."),
    });
    const poll = window.setInterval(() => void loadRun(streamRunId), 5000);
    return () => {
      handle.close();
      window.clearInterval(poll);
    };
  }, [streamRunId, loadRun]);

  const startLearning = async () => {
    if (!selectedSource) return;
    setBusy(true);
    setError("");
    setActionMessage("");
    try {
      const result = await learnSource(selectedSource);
      const newRunId = String((result.run as { id?: string })?.id ?? "");
      setActionMessage("Aprendizaje iniciado.");
      await load();
      if (newRunId) {
        const updated = new URLSearchParams(params);
        updated.set("view", "runs");
        updated.set("run", newRunId);
        setParams(updated, { replace: true });
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "No se pudo iniciar el aprendizaje.");
    } finally {
      setBusy(false);
    }
  };

  const cancelRun = async () => {
    if (!run) return;
    setBusy(true);
    try {
      await cancelLearning(run.id);
      setActionMessage("Aprendizaje cancelado.");
      await loadRun(run.id);
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "No se pudo cancelar el run.");
    } finally {
      setBusy(false);
    }
  };

  const selectedRunSource = sources.find(
    (source) => source.source_id === run?.catalog_source_id
  );

  return (
    <div className="flex flex-col gap-4">
      <Panel flat className="p-3">
        <div className="flex flex-col gap-2 sm:flex-row sm:items-center">
          <Select
            aria-label="Fuente para aprender"
            value={selectedSource}
            onChange={(e) => setSelectedSource(e.target.value)}
            className="sm:max-w-[320px]"
          >
            <option value="">Selecciona una fuente…</option>
            {learnableSources.map((source) => (
              <option key={source.source_id} value={source.source_id}>
                {sourceLabel(source)}
                {source.active_run ? " · aprendizaje en curso" : ""}
              </option>
            ))}
          </Select>
          <Button
            variant="primary"
            leadingIcon={ArrowsClockwise}
            disabled={!selectedSource || busy}
            onClick={() => void startLearning()}
          >
            Aprender / actualizar
          </Button>
          <span className="text-xs text-muted">
            {learnableSources.length === 0
              ? "No hay fuentes SQL reales con discovery. Los archivos indexados se consultan en Fuentes."
              : "El aprendizaje corre en background y produce conocimiento persistente."}
          </span>
        </div>
      </Panel>

      {actionMessage && <p className="text-sm text-ok">{actionMessage}</p>}
      <ErrorInline message={error} className="mb-0" />

      {loading && (
        <div className="flex flex-col gap-3" aria-busy="true">
          <Skeleton className="h-[120px] rounded-lg" />
          <Skeleton className="h-[240px] rounded-lg" />
        </div>
      )}

      {!loading && runs.length === 0 && !error && (
        <Panel>
          <EmptyState
            icon={Lightning}
            title="Sin aprendizajes ejecutados"
            body="Ejecuta aprendizaje sobre una fuente para descubrir schema, entidades, relaciones y reglas."
            action={
              <ButtonLink to="/knowledge/sources?new=1" variant="primary" leadingIcon={Plus}>
                Añadir fuente
              </ButtonLink>
            }
          />
        </Panel>
      )}

      {!loading && runs.length > 0 && (
        <div className="grid grid-cols-1 gap-4 xl:grid-cols-[380px_1fr]">
          <Panel className="overflow-hidden">
            <PanelHeader title="Runs" description="Más recientes primero." />
            <ul className="flex flex-col">
              {runs.map((item) => {
                const active = item.id === activeRunId;
                return (
                  <li key={item.id}>
                    <button
                      type="button"
                      className={cn(
                        "flex w-full flex-col gap-1 border-b border-border px-4 py-3 text-left last:border-0",
                        active ? "bg-soft/70" : "hover:bg-soft/40"
                      )}
                      onClick={() => {
                        const updated = new URLSearchParams(params);
                        updated.set("view", "runs");
                        updated.set("run", item.id);
                        setParams(updated, { replace: true });
                      }}
                    >
                      <span className="flex items-center justify-between gap-2">
                        <Badge tone={runTone(item.status)}>{item.status}</Badge>
                        <span className="text-xs text-muted">
                          {fmtDateTime(item.created_at)}
                        </span>
                      </span>
                      <span className="text-xs text-muted">
                        {stageLabel(item.current_stage)} · {item.overall_progress}%
                      </span>
                    </button>
                  </li>
                );
              })}
            </ul>
          </Panel>

          <div className="flex flex-col gap-4">
            {run ? (
              <>
                <Panel>
                  <div className="flex flex-col gap-3 p-4">
                    <div className="flex flex-wrap items-center justify-between gap-2">
                      <div>
                        <p className="text-sm text-text">
                          {selectedRunSource ? sourceLabel(selectedRunSource) : "Fuente"} ·{" "}
                          <span className="text-muted">{run.id.slice(0, 8)}</span>
                        </p>
                        <p className="text-xs text-muted">
                          {run.started_at ? `Inicio ${fmtDateTime(run.started_at)}` : "En cola"}
                          {run.finished_at ? ` · Fin ${fmtDateTime(run.finished_at)}` : ""}
                        </p>
                      </div>
                      {ACTIVE_STATUSES.has(run.status) && (
                        <Button variant="danger" disabled={busy} onClick={() => void cancelRun()}>
                          Cancelar
                        </Button>
                      )}
                    </div>
                    <LearningProgress
                      overallProgress={run.overall_progress}
                      currentStage={run.current_stage}
                      stageProgress={run.stage_progress}
                      status={run.status}
                    />
                    <div className="grid grid-cols-2 gap-2 text-xs text-muted sm:grid-cols-4">
                      <span>{run.tables_analyzed} tablas</span>
                      <span>{run.entities_detected} entidades</span>
                      <span>{run.fields_detected} campos</span>
                      <span>{run.relationships_detected} relaciones</span>
                    </div>
                  </div>
                </Panel>

                <Panel>
                  <PanelHeader
                    title="Etapas"
                    description="Estado real de cada stage del pipeline (modo técnico)."
                  />
                  <div className="panel-body">
                    {run.steps && run.steps.length > 0 ? (
                      <LearningStageTimeline steps={run.steps} />
                    ) : (
                      <p className="text-sm text-muted">Sin etapas registradas todavía.</p>
                    )}
                  </div>
                </Panel>

                <Panel>
                  <PanelHeader
                    title="Eventos"
                    description="Eventos durables + live del run seleccionado."
                  />
                  <div className="panel-body">
                    <LearningActivityFeed
                      runId={run.id}
                      sourceId={run.catalog_source_id}
                      liveEvents={liveEvents}
                      refreshKey={run.overall_progress}
                    />
                  </div>
                </Panel>
              </>
            ) : (
              <Panel>
                <p className="panel-body text-sm text-muted">
                  Selecciona un run para ver sus etapas y eventos.
                </p>
              </Panel>
            )}
          </div>
        </div>
      )}

      {!loading && compilations.length > 0 && (
        <Panel className="overflow-hidden">
          <PanelHeader
            title="Compilaciones de conocimiento"
            description="Qué produjo cada documento. Este es el modo técnico del pipeline."
          />
          <ul className="flex flex-col">
            {compilations.map((item) => (
              <li
                key={item.id}
                className="flex flex-col gap-1 border-b border-border px-4 py-3 last:border-0"
              >
                <span className="flex items-center justify-between gap-2">
                  <span className="truncate text-sm font-medium">
                    {item.document_title || item.document_id || "Documento"}
                  </span>
                  <Badge tone={item.status === "completed" ? "ok" : "warn"}>
                    {item.status}
                  </Badge>
                </span>
                <span className="flex flex-wrap gap-x-3 gap-y-1 text-xs text-muted">
                  <span>{item.counts.entities} entidades</span>
                  <span>{item.counts.facts} hechos</span>
                  <span>{item.counts.relationships} relaciones</span>
                  <span>{item.counts.rules} reglas</span>
                  <span>{item.counts.evidence} evidencias</span>
                  <span>{Math.round(item.duration_ms)} ms</span>
                </span>
                {item.error && <span className="text-xs text-danger">{item.error}</span>}
              </li>
            ))}
          </ul>
        </Panel>
      )}
    </div>
  );
}

export default function KnowledgeActivityPage() {
  const [params, setParams] = useSearchParams();
  const view = params.get("view") === "runs" ? "runs" : "feed";

  const setView = (next: "feed" | "runs") => {
    const updated = new URLSearchParams(params);
    if (next === "runs") updated.set("view", "runs");
    else {
      updated.delete("view");
      updated.delete("run");
    }
    setParams(updated, { replace: true });
  };

  return (
    <KnowledgeLayout>
      <PageHeader
        title={KNOWLEDGE_HEADINGS.activity}
        subtitle="Qué está aprendiendo ZENT, qué acaba de descubrir y qué cambió. Los runs del pipeline viven en modo técnico."
        actions={
          <>
            <Button
              size="sm"
              variant={view === "feed" ? "secondary" : "ghost"}
              onClick={() => setView("feed")}
            >
              Aprendizaje
            </Button>
            <Button
              size="sm"
              variant={view === "runs" ? "secondary" : "ghost"}
              onClick={() => setView("runs")}
            >
              Modo técnico
            </Button>
          </>
        }
      />
      {view === "feed" ? <FeedView /> : <RunsView />}
    </KnowledgeLayout>
  );
}
