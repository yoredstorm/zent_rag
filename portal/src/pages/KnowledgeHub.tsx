import { BookOpen, Compass, GearSix, Lightbulb, Plus, Play, Warning } from "@phosphor-icons/react";
import { useEffect, useState } from "react";
import { api } from "../api";
import { useAuth } from "../auth";
import { KnowledgeLayout } from "../components/KnowledgeLayout";
import {
  Badge,
  Button,
  EmptyState,
  ErrorInline,
  Field,
  Input,
  Metric,
  MetricGrid,
  PageHeader,
  Panel,
  PanelHeader,
  Progress,
  Select,
  Skeleton,
  StatusBadge,
  Textarea,
} from "../components/ui";
import { KNOWLEDGE_HEADINGS } from "../lib/knowledgeNav";
import { fmtDateTime } from "../lib/format";

type Source = {
  id: string;
  name: string;
  source_type: string;
  config: Record<string, unknown>;
  refresh_interval_h: number;
  last_refresh_at: string | null;
  next_refresh_at: string | null;
  status: string;
  documents: number;
};
type Coverage = {
  total_documents: number;
  sources: {
    name: string;
    source_type: string;
    documents: number;
    avg_confidence: number;
    avg_freshness: number;
  }[];
  categories: { category: string; documents: number }[];
  last_refreshes: {
    source: string;
    status: string;
    added: number;
    duplicated: number;
    started_at: string;
  }[];
  open_gaps: number;
  gap_occurrences: number;
};
type Gap = {
  id: string;
  query: string;
  intent: string | null;
  occurrences: number;
  status: string;
  created_at: string;
  last_seen_at: string;
};

function railState(status: string): "ready" | "warning" | "queued" {
  if (status === "active") return "ready";
  if (status === "paused") return "warning";
  return "queued";
}

export default function KnowledgeHubPage() {
  const { session } = useAuth();
  const [sources, setSources] = useState<Source[]>([]);
  const [coverage, setCoverage] = useState<Coverage | null>(null);
  const [gaps, setGaps] = useState<Gap[]>([]);
  const [draft, setDraft] = useState({
    name: "",
    source_type: "url",
    config: "",
    refresh_interval_h: 24,
  });
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState("");
  const [error, setError] = useState("");

  async function load() {
    if (!session) return;
    try {
      const [s, c, g] = await Promise.all([
        api<{ sources: Source[] }>("/api/v1/knowledge-hub/sources", {
          token: session.token,
          organizationId: session.organizationId,
        }),
        api<Coverage>("/api/v1/knowledge-hub/coverage", {
          token: session.token,
          organizationId: session.organizationId,
        }),
        api<{ gaps: Gap[] }>("/api/v1/knowledge-hub/gaps", {
          token: session.token,
          organizationId: session.organizationId,
        }),
      ]);
      setSources(s.sources || []);
      setCoverage(c);
      setGaps(g.gaps || []);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Error");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    void load();
    const id = setInterval(() => void load(), 20000);
    return () => clearInterval(id);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [session]);

  async function create() {
    if (!session || !draft.name) return;
    setBusy("create");
    setError("");
    try {
      let config: Record<string, unknown> = {};
      try {
        config = JSON.parse(draft.config || "{}");
      } catch {
        setError("config no es JSON válido");
        setBusy("");
        return;
      }
      const out = await api<{ source_id: string }>("/api/v1/knowledge-hub/sources", {
        method: "POST",
        token: session.token,
        organizationId: session.organizationId,
        body: JSON.stringify({
          name: draft.name,
          source_type: draft.source_type,
          config,
          refresh_interval_h: draft.refresh_interval_h,
        }),
      });
      setError(`Fuente creada: ${out.source_id.slice(0, 8)}…`);
      setDraft({ name: "", source_type: "url", config: "", refresh_interval_h: 24 });
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Error");
    } finally {
      setBusy("");
    }
  }

  async function act(id: string, action: "refresh" | "pause" | "resume") {
    if (!session) return;
    setBusy(`${action}-${id.slice(0, 6)}`);
    setError("");
    try {
      const out = await api<Record<string, unknown>>(`/api/v1/knowledge-hub/sources/${id}/${action}`, {
        method: "POST",
        token: session.token,
        organizationId: session.organizationId,
      });
      setError(`${action}: ${JSON.stringify(out).slice(0, 100)}`);
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Error");
    } finally {
      setBusy("");
    }
  }

  async function resolveGap(id: string) {
    if (!session) return;
    setError("");
    try {
      await api(`/api/v1/knowledge-hub/gaps/${id}/resolve`, {
        method: "POST",
        token: session.token,
        organizationId: session.organizationId,
      });
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Error");
    }
  }

  const maxDocs = Math.max(1, ...(coverage?.sources ?? []).map((s) => s.documents));

  return (
    <KnowledgeLayout>
      <div className="space-y-5">
        <PageHeader
          title={KNOWLEDGE_HEADINGS.hub}
          subtitle="Auto-descubrimiento de fuentes, deduplicación semántica y curación de conocimiento."
        />
        <ErrorInline message={error} className="mb-0" />

        {loading ? (
          <Panel>
            <div className="panel-body">
              <Skeleton className="h-40" />
            </div>
          </Panel>
        ) : (
          <div className="grid grid-cols-1 gap-4 lg:grid-cols-[360px_minmax(0,1fr)] lg:items-start">
            <div className="space-y-4">
              <Panel>
                <PanelHeader
                  title={
                    <span className="flex items-center gap-2">
                      <GearSix size={15} className="text-faint" aria-hidden />
                      Nueva fuente
                    </span>
                  }
                  description="Una fuente alimenta la cobertura con documentos reales."
                />
                <div className="panel-body flex flex-col gap-4">
                  <Field label="Nombre">
                    <Input
                      value={draft.name}
                      onChange={(e) => setDraft((d) => ({ ...d, name: e.target.value }))}
                      autoComplete="off"
                    />
                  </Field>
                  <Field label="Tipo">
                    <Select
                      value={draft.source_type}
                      onChange={(e) => setDraft((d) => ({ ...d, source_type: e.target.value }))}
                    >
                      {["url", "rss", "repo", "s3", "manual"].map((t) => (
                        <option key={t} value={t}>
                          {t}
                        </option>
                      ))}
                    </Select>
                  </Field>
                  <Field label="Refresco (horas)">
                    <Input
                      type="number"
                      min={1}
                      value={draft.refresh_interval_h}
                      onChange={(e) =>
                        setDraft((d) => ({ ...d, refresh_interval_h: Number(e.target.value) }))
                      }
                    />
                  </Field>
                  <Field label="Configuración (JSON)" hint="Debe ser un objeto JSON válido.">
                    <Textarea
                      className="min-h-24 font-mono text-[11px]"
                      placeholder='{"url": "https://docs.miempresa.com", "prefix": "Docs"}'
                      value={draft.config}
                      onChange={(e) => setDraft((d) => ({ ...d, config: e.target.value }))}
                    />
                  </Field>
                  <Button
                    variant="primary"
                    leadingIcon={Plus}
                    loading={busy === "create"}
                    disabled={!draft.name}
                    onClick={() => void create()}
                  >
                    Crear fuente
                  </Button>
                </div>
              </Panel>

              <Panel>
                <PanelHeader
                  title={
                    <span className="flex items-center gap-2">
                      <BookOpen size={15} className="text-faint" aria-hidden />
                      Fuentes
                    </span>
                  }
                  actions={<Badge tone="neutral">{sources.length}</Badge>}
                />
                <div className="panel-body flex flex-col gap-2">
                  {sources.map((s) => (
                    <div key={s.id} className="state-rail" data-state={railState(s.status)}>
                      <div className="flex flex-wrap items-center gap-2">
                        <span className="min-w-0 flex-1 truncate text-[13px] font-medium text-text">
                          {s.name}
                        </span>
                        <StatusBadge status={s.status} />
                      </div>
                      <p className="mt-0.5 text-[11px] text-faint">
                        {s.source_type} · {s.documents} docs · cada {s.refresh_interval_h}h
                      </p>
                      <p className="mt-0.5 text-[11px] text-faint">
                        Último: {s.last_refresh_at ? fmtDateTime(s.last_refresh_at) : "—"} · Próximo:{" "}
                        {s.next_refresh_at ? fmtDateTime(s.next_refresh_at) : "—"}
                      </p>
                      <div className="mt-1.5 flex flex-wrap gap-1">
                        <Button
                          variant="ghost"
                          size="sm"
                          leadingIcon={Play}
                          disabled={!!busy}
                          onClick={() => void act(s.id, "refresh")}
                        >
                          Refrescar
                        </Button>
                        {s.status === "active" ? (
                          <Button
                            variant="ghost"
                            size="sm"
                            disabled={!!busy}
                            onClick={() => void act(s.id, "pause")}
                          >
                            Pausar
                          </Button>
                        ) : (
                          <Button
                            variant="ghost"
                            size="sm"
                            disabled={!!busy}
                            onClick={() => void act(s.id, "resume")}
                          >
                            Reanudar
                          </Button>
                        )}
                      </div>
                    </div>
                  ))}
                  {sources.length === 0 && (
                    <EmptyState
                      compact
                      icon={BookOpen}
                      title="Sin fuentes"
                      body="Creá una fuente para empezar a medir cobertura."
                    />
                  )}
                </div>
              </Panel>
            </div>

            <div className="space-y-4">
              <MetricGrid cols={4}>
                <Metric
                  label="Documentos"
                  value={coverage?.total_documents ?? 0}
                  size="md"
                />
                <Metric label="Huecos abiertos" value={coverage?.open_gaps ?? 0} size="md" />
                <Metric
                  label="Consultas sin respuesta"
                  value={coverage?.gap_occurrences ?? 0}
                  size="md"
                />
                <Metric label="Fuentes" value={coverage?.sources.length ?? 0} size="md" />
              </MetricGrid>

              <div className="grid grid-cols-1 gap-4 xl:grid-cols-2">
                <Panel>
                  <PanelHeader
                    title={
                      <span className="flex items-center gap-2">
                        <Compass size={15} className="text-faint" aria-hidden />
                        Cobertura por fuente
                      </span>
                    }
                  />
                  <div className="panel-body">
                    {(coverage?.sources ?? []).length === 0 ? (
                      <p className="text-xs text-muted">Creá una fuente y refrescala para ver cobertura.</p>
                    ) : (
                      <div className="space-y-3">
                        {(coverage?.sources ?? []).map((s) => (
                          <div key={s.name}>
                            <Progress
                              value={s.documents}
                              max={maxDocs}
                              label={s.name}
                              showValue
                            />
                            <p className="mt-1 text-[11px] text-faint">
                              {s.documents} docs · conf {s.avg_confidence} · fresh {s.avg_freshness}
                            </p>
                          </div>
                        ))}
                      </div>
                    )}
                    {(coverage?.categories ?? []).length > 0 && (
                      <>
                        <p className="eyebrow mt-4 mb-2">Por categoría</p>
                        <div className="flex flex-wrap gap-1">
                          {(coverage?.categories ?? []).map((cat) => (
                            <Badge key={cat.category} tone="neutral">
                              {cat.category} · {cat.documents}
                            </Badge>
                          ))}
                        </div>
                      </>
                    )}
                  </div>
                </Panel>

                <Panel>
                  <PanelHeader
                    title={
                      <span className="flex items-center gap-2">
                        <Lightbulb size={15} className="text-faint" aria-hidden />
                        Huecos de conocimiento
                      </span>
                    }
                    actions={<Badge tone="neutral">{gaps.length}</Badge>}
                  />
                  <div className="panel-body">
                    <div className="space-y-2">
                      {gaps.map((g) => (
                        <div key={g.id} className="state-rail" data-state="warning">
                          <div className="flex flex-wrap items-center gap-2">
                            <Warning size={12} className="shrink-0 text-warn" aria-hidden />
                            <span className="min-w-0 flex-1 truncate text-[13px] text-text">
                              {g.query}
                            </span>
                            <Badge tone="warn">×{g.occurrences}</Badge>
                            <Button
                              variant="ghost"
                              size="sm"
                              onClick={() => void resolveGap(g.id)}
                            >
                              Resolver
                            </Button>
                          </div>
                          {g.intent && (
                            <p className="mt-0.5 text-[11px] text-faint">Intención: {g.intent}</p>
                          )}
                        </div>
                      ))}
                      {gaps.length === 0 && (
                        <p className="text-xs text-muted">
                          Sin huecos: las consultas sin intención detectada generan huecos.
                        </p>
                      )}
                    </div>
                    {(coverage?.last_refreshes ?? []).length > 0 && (
                      <>
                        <p className="eyebrow mt-4 mb-2">Últimos refrescos</p>
                        <div className="space-y-1">
                          {(coverage?.last_refreshes ?? []).slice(0, 4).map((r, i) => (
                            <p
                              key={`${r.source}-${i}`}
                              className="rounded-sm bg-soft px-2 py-1 text-[11px] text-faint"
                            >
                              {r.source} · {r.status} · +{r.added} · {r.duplicated} dup
                            </p>
                          ))}
                        </div>
                      </>
                    )}
                  </div>
                </Panel>
              </div>
            </div>
          </div>
        )}
      </div>
    </KnowledgeLayout>
  );
}
