import {
  ArrowRight,
  Brain,
  Database,
  MagnifyingGlass,
  Plus,
  WarningCircle,
} from "@phosphor-icons/react";
import { useCallback, useEffect, useMemo, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
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
  Skeleton,
} from "../../components/ui";
import { KnowledgeLayout } from "../../components/KnowledgeLayout";
import { KNOWLEDGE_HEADINGS } from "../../lib/knowledgeNav";
import {
  fetchKnowledgeOverview,
  objectTypeLabel,
  statusTone,
  type KnowledgeHealth,
  type KnowledgeOverview,
} from "../../lib/knowledgeModel";
import { fmtDateTime } from "../../lib/format";

function healthTone(overall: number | null): string {
  if (overall == null) return "text-muted";
  if (overall >= 75) return "text-ok";
  if (overall >= 50) return "text-warn";
  return "text-danger";
}

function DimensionRow({ dimension }: { dimension: KnowledgeHealth["dimensions"][number] }) {
  const measured = dimension.measured && dimension.score != null;
  return (
    <details className="group border-b border-border last:border-0">
      <summary className="flex cursor-pointer list-none items-center gap-3 py-2.5">
        <span className="min-w-0 flex-1 truncate text-sm text-text">{dimension.label}</span>
        {measured ? (
          <span className="mono text-sm tabular-nums text-text">{Math.round(dimension.score!)}</span>
        ) : (
          <Badge tone="neutral">No medido</Badge>
        )}
        <ArrowRight
          size={13}
          className="shrink-0 text-muted transition-transform group-open:rotate-90"
          aria-hidden
        />
      </summary>
      <div className="pb-3 pl-0 text-xs leading-relaxed text-muted">
        <p>
          <span className="font-medium text-text">Por qué:</span> {dimension.reason || "Sin detalle."}
        </p>
        {dimension.formula && (
          <p className="mt-1">
            <span className="font-medium text-text">Fórmula:</span>{" "}
            <span className="mono">{dimension.formula}</span>
          </p>
        )}
        {dimension.issues.length > 0 && (
          <ul className="mt-1 list-disc pl-4">
            {dimension.issues.map((issue) => (
              <li key={issue}>{issue}</li>
            ))}
          </ul>
        )}
        {!measured && dimension.missing.length > 0 && (
          <p className="mt-1">Falta medir: {dimension.missing.join(", ")}.</p>
        )}
      </div>
    </details>
  );
}

export default function KnowledgeOverviewPage() {
  const navigate = useNavigate();
  const [overview, setOverview] = useState<KnowledgeOverview | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [query, setQuery] = useState("");

  const load = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const data = await fetchKnowledgeOverview();
      setOverview(data);
    } catch (err) {
      setOverview(null);
      setError(
        err instanceof Error
          ? err.message
          : "No pudimos obtener el conocimiento de tu organización."
      );
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const domains = useMemo(
    () => (overview?.domains ?? []).filter((d) => d.objects > 0),
    [overview]
  );

  const submitSearch = (event: React.FormEvent) => {
    event.preventDefault();
    const value = query.trim();
    if (!value) return;
    navigate(`/knowledge/model?q=${encodeURIComponent(value)}`);
  };

  return (
    <KnowledgeLayout>
      <PageHeader
        title={KNOWLEDGE_HEADINGS.overview}
        subtitle={
          overview?.headline ||
          "Explora qué sabe Zent de tu negocio, qué falta y qué necesita tu atención."
        }
        actions={
          <>
            <ButtonLink to="/knowledge/add" variant="primary" leadingIcon={Plus}>
              Añadir fuente
            </ButtonLink>
            <ButtonLink to="/knowledge/model" variant="secondary" leadingIcon={Brain}>
              Explorar modelo
            </ButtonLink>
          </>
        }
      />

      {loading && (
        <div className="flex flex-col gap-4" aria-busy="true">
          <Skeleton className="h-[168px] rounded-lg" />
          <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
            <Skeleton className="h-[220px] rounded-lg" />
            <Skeleton className="h-[220px] rounded-lg" />
          </div>
        </div>
      )}

      {!loading && error && (
        <div data-testid="knowledge-overview-error">
          <ErrorInline
            className="mb-0"
            message={`No pudimos obtener el conocimiento de tu organización. ${error}`}
          />
          <div className="mt-3">
            <Button variant="secondary" onClick={() => void load()}>
              Reintentar
            </Button>
          </div>
        </div>
      )}

      {!loading && !error && overview && overview.state === "empty" && (
        <Panel>
          {overview.counts.indexed_documents > 0 ? (
            <EmptyState
              icon={Database}
              title="Tus archivos están indexados; falta el modelo de negocio"
              body={`Zent indexó ${overview.counts.indexed_documents} documento(s) de ${overview.counts.indexed_sources} fuente(s) y los usa para buscar y responder. El modelo de negocio (entidades, relaciones, reglas y métricas) se construye desde fuentes estructuradas: una base de datos SQL o el catálogo de Excel/CSV.`}
              action={
                <ButtonLink to="/knowledge/sources" variant="primary">
                  Ver fuentes
                </ButtonLink>
              }
              secondaryAction={
                <ButtonLink to="/knowledge/documents" variant="secondary">
                  Ver documentos
                </ButtonLink>
              }
            />
          ) : (
            <EmptyState
              icon={Database}
              title="Zent todavía no tiene conocimiento de tu negocio"
              body="Conecta una base de datos SQL y Zent construirá entidades, relaciones, reglas y métricas verificables. Los archivos (PDF, Excel) se indexan para búsqueda."
              action={
                <ButtonLink to="/knowledge/add" variant="primary" leadingIcon={Plus}>
                  Añadir fuente
                </ButtonLink>
              }
              secondaryAction={
                <ButtonLink to="/knowledge/sources" variant="secondary">
                  Ver fuentes
                </ButtonLink>
              }
            />
          )}
        </Panel>
      )}

      {!loading && !error && overview && overview.state !== "empty" && (
        <div className="flex flex-col gap-4">
          <Panel>
            <div className="flex flex-col gap-5 p-5 lg:flex-row lg:items-start lg:justify-between">
              <div className="min-w-0">
                <p className="eyebrow">Knowledge Health</p>
                <div className="mt-1 flex items-end gap-3">
                  <span className={cn("stat-value", healthTone(overview.health.overall))}>
                    {overview.health.overall != null
                      ? Math.round(overview.health.overall)
                      : "—"}
                  </span>
                  <span className="pb-1 text-xs text-muted">
                    {overview.health.measured_dimensions} de{" "}
                    {overview.health.total_dimensions} dimensiones medidas
                  </span>
                </div>
                <p className="prose-measure mt-2 text-sm text-muted">
                  {overview.counts.objects} objetos de negocio ·{" "}
                  {overview.counts.assertions} afirmaciones · {overview.counts.evidence}{" "}
                  evidencias · {overview.counts.edges} relaciones
                </p>
                <form className="mt-4 flex max-w-xl gap-2" onSubmit={submitSearch}>
                  <label className="sr-only" htmlFor="knowledge-search">
                    Buscar en el conocimiento
                  </label>
                  <input
                    id="knowledge-search"
                    className="input"
                    placeholder="Buscar en el conocimiento (cliente, ventas, margen...)"
                    value={query}
                    onChange={(e) => setQuery(e.target.value)}
                  />
                  <Button
                    type="submit"
                    variant="secondary"
                    leadingIcon={MagnifyingGlass}
                    disabled={!query.trim()}
                  >
                    Buscar
                  </Button>
                </form>
              </div>
              <div className="w-full max-w-md shrink-0 lg:w-[360px]">
                <p className="eyebrow mb-1">Dimensiones</p>
                {overview.health.dimensions.map((dimension) => (
                  <DimensionRow key={dimension.key} dimension={dimension} />
                ))}
              </div>
            </div>
          </Panel>

          <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
            <Panel>
              <PanelHeader
                title="Dominios"
                description="Áreas del negocio detectadas o definidas."
                actions={
                  <Link to="/knowledge/model?type=domain" className="text-xs underline underline-offset-2">
                    Ver todos
                  </Link>
                }
              />
              <div className="panel-body">
                {domains.length === 0 ? (
                  <p className="text-sm text-muted">
                    Todavía no hay dominios con objetos. Ejecuta aprendizaje sobre una
                    fuente para detectarlos.
                  </p>
                ) : (
                  <ul className="flex flex-col gap-3">
                    {domains.slice(0, 6).map((domain) => (
                      <li key={domain.name}>
                        <Link
                          to={`/knowledge/model?domain=${encodeURIComponent(domain.name)}`}
                          className="flex items-center justify-between gap-3"
                        >
                          <span className="truncate text-sm text-text">{domain.name}</span>
                          <span className="flex items-center gap-2 text-xs text-muted">
                            <span>{domain.objects} objetos</span>
                            {domain.verified > 0 && (
                              <Badge tone="ok">{domain.verified} verificados</Badge>
                            )}
                            {domain.avg_confidence != null && (
                              <span className="mono">
                                {Math.round(domain.avg_confidence * 100)}%
                              </span>
                            )}
                          </span>
                        </Link>
                      </li>
                    ))}
                  </ul>
                )}
              </div>
            </Panel>

            <Panel>
              <PanelHeader
                title="Necesita tu atención"
                description="Problemas reales del conocimiento, no decoración."
                actions={
                  <Link to="/knowledge/quality" className="text-xs underline underline-offset-2">
                    Ir a Calidad
                  </Link>
                }
              />
              <div className="panel-body">
                {overview.attention.length === 0 ? (
                  <p className="text-sm text-muted">
                    Sin conflictos, gaps críticos ni fuentes degradadas.
                  </p>
                ) : (
                  <ul className="flex flex-col gap-2.5">
                    {overview.attention.map((item) => (
                      <li key={`${item.kind}-${item.title}`}>
                        <Link
                          to={item.href}
                          className="flex items-center gap-2 text-sm text-text hover:underline"
                        >
                          <WarningCircle
                            size={15}
                            className={cn(
                              "shrink-0",
                              item.severity === "high" ? "text-danger" : "text-warn"
                            )}
                            aria-hidden
                          />
                          <span className="min-w-0 flex-1">{item.title}</span>
                          <ArrowRight size={13} className="text-muted" aria-hidden />
                        </Link>
                      </li>
                    ))}
                  </ul>
                )}
              </div>
            </Panel>
          </div>

          <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
            <Panel>
              <PanelHeader
                title="Último aprendizaje"
                description="Artefactos persistentes del run más reciente."
                actions={
                  <Link to="/knowledge/activity" className="text-xs underline underline-offset-2">
                    Ver actividad
                  </Link>
                }
              />
              <div className="panel-body">
                {overview.last_learning ? (
                  <div className="flex flex-col gap-2 text-sm">
                    <div className="flex flex-wrap items-center gap-2">
                      <Badge
                        tone={
                          overview.last_learning.status === "completed"
                            ? "ok"
                            : overview.last_learning.status === "failed"
                              ? "danger"
                              : "info"
                        }
                      >
                        {overview.last_learning.status}
                      </Badge>
                      <span className="text-muted">
                        {fmtDateTime(overview.last_learning.finished_at || overview.last_learning.created_at)}
                      </span>
                    </div>
                    <p className="text-muted">
                      {overview.last_learning.entities_detected} entidades ·{" "}
                      {overview.last_learning.fields_detected} campos ·{" "}
                      {overview.last_learning.relationships_detected} relaciones
                      {overview.last_learning.duration_ms != null &&
                        ` · ${Math.round(overview.last_learning.duration_ms / 1000)}s`}
                    </p>
                    {overview.last_learning.status === "failed" && (
                      <p className="text-danger">
                        El último aprendizaje falló. Revisa la actividad para ver el
                        diagnóstico.
                      </p>
                    )}
                  </div>
                ) : (
                  <p className="text-sm text-muted">
                    No hay ningún aprendizaje ejecutado todavía. El modelo actual proviene
                    del discovery de schema.
                  </p>
                )}
              </div>
            </Panel>

            <Panel>
              <PanelHeader
                title="Cambios recientes"
                description="Objetos, afirmaciones y eventos del conocimiento."
              />
              <div className="panel-body">
                {overview.recent.length === 0 ? (
                  <p className="text-sm text-muted">Sin cambios registrados.</p>
                ) : (
                  <ul className="flex flex-col gap-2.5">
                    {overview.recent.slice(0, 8).map((item) => (
                      <li key={`${item.kind}-${item.id}`} className="flex items-start gap-2">
                        <span className="mt-1.5 h-1.5 w-1.5 shrink-0 rounded-full bg-accent" aria-hidden />
                        <div className="min-w-0 flex-1">
                          <p className="truncate text-sm text-text">{item.title}</p>
                          <p className="text-xs text-muted">
                            {item.kind === "event"
                              ? item.type
                              : objectTypeLabel(item.type)}
                            {item.at ? ` · ${fmtDateTime(item.at)}` : ""}
                          </p>
                        </div>
                        {item.status && (
                          <span className={cn("badge", statusTone(item.status))}>
                            {item.status}
                          </span>
                        )}
                      </li>
                    ))}
                  </ul>
                )}
              </div>
            </Panel>
          </div>
        </div>
      )}
    </KnowledgeLayout>
  );
}
