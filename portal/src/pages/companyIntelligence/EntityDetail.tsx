import { useEffect, useState } from "react";
import { Link, useParams, useSearchParams } from "react-router-dom";
import { api } from "../../api";
import { useAuth } from "../../auth";
import { CompanyIntelligenceLayout } from "../../components/CompanyIntelligenceLayout";
import { PageTabs } from "../../components/PageTabs";
import {
  Badge,
  ErrorInline,
  PageHeader,
  Panel,
  PanelHeader,
  SkeletonBlock,
  WarningInline,
} from "../../components/ui";
import { fmtNum, timeAgo } from "../../lib/format";
import {
  certaintyNote,
  entityTypeLabel,
  gapLabel,
  groupLabel,
  statusLabelFor,
  statusToneFor,
} from "./companyCopy";

type Edge = {
  id: string;
  relationship_type: string;
  direction: string;
  from: { id: string; name: string; type: string };
  to: { id: string; name: string; type: string };
  status: string;
  confidence: number | null;
  source: string;
  valid_from: string | null;
  valid_to: string | null;
  confirmed: boolean;
};

type Detail = {
  entity: {
    id: string;
    entity_type: string;
    canonical_name: string;
    display_name: string;
    description: string;
    domain: string;
    status: string;
    confidence: number | null;
    authority_level: string | null;
    aliases: string[];
    valid_from: string | null;
    valid_to: string | null;
    last_observed_at: string;
  };
  incoming: Edge[];
  outgoing: Edge[];
  related: Record<string, Array<{ id: string; display_name: string; entity_type: string; status: string }>>;
  technical_mappings: Array<{
    id: string;
    target: string;
    target_type: string;
    values: string[];
    predicate: string;
    status: string;
    confidence: number | null;
  }>;
  authority: Array<{ source_name: string; authority_level: string; source_type: string }>;
  memory: Array<{
    id: string;
    pattern_key: string;
    title: string;
    status: string;
    success_rate: number;
    support_count: number;
  }>;
  knowledge_gaps: Array<{ id: string; gap_kind: string; subject: string; detail: string }>;
};

type Impact = {
  direct: Array<{
    relationship_type: string;
    from: string;
    to: string;
    status: string;
    certainty: string;
  }>;
  affected: Record<string, Array<{ id: string; name: string; entity_type: string }>>;
  paths: Array<{
    target_id: string;
    target: string;
    hops: number;
    certainty: string;
    explanation: Array<{ from: string; relationship_type: string; to: string; status: string }>;
  }>;
  truncated: boolean;
};

type ProcessPage = {
  designed: { steps: Array<{ name: string; order: number }> } | null;
  observed: {
    steps: Array<{ name: string; frequency: number; runs: number }>;
    runs_observed: number;
  } | null;
  systems: Array<{ id: string; name: string; status: string }>;
  agents: Array<{ id: string; name: string }>;
  rules: Array<{ id: string; name: string }>;
  events: Array<{ id: string; name: string }>;
  workflows: Array<{ id: string; name: string }>;
  deviation: {
    available: boolean;
    runs?: number;
    canonical_sequence?: string[];
    rework_frequency?: number;
    note?: string;
  };
};

type ChangesView = {
  compared_to: string;
  relationships_added: Array<{ relationship_type: string; other: string; status: string }>;
  relationships_removed: Array<{ relationship_type: string; other: string; status: string }>;
  history: Array<{ id: string; relationship_type: string; status: string; created_at: string }>;
};

const TABS = [
  { id: "overview", label: "Resumen" },
  { id: "dependencies", label: "Relaciones" },
  { id: "impact", label: "Impacto" },
  { id: "process", label: "Proceso" },
  { id: "memory", label: "Aprendizaje" },
  { id: "changes", label: "Cambios" },
];

export default function CompanyEntityDetailPage() {
  const { session } = useAuth();
  const { entityId = "" } = useParams();
  const [params, setParams] = useSearchParams();
  const tab = params.get("tab") || "overview";
  const [detail, setDetail] = useState<Detail | null>(null);
  const [impact, setImpact] = useState<Impact | null>(null);
  const [process, setProcess] = useState<ProcessPage | null>(null);
  const [changes, setChanges] = useState<ChangesView | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  useEffect(() => {
    if (!session || !entityId) return;
    (async () => {
      setLoading(true);
      setError("");
      try {
        const base = { token: session.token, organizationId: session.organizationId };
        const data = await api<Detail>(
          `/api/v1/company-intelligence/entities/${entityId}`,
          base,
        );
        setDetail(data);
      } catch (err) {
        setError(err instanceof Error ? err.message : "Error cargando la entidad");
        setDetail(null);
      } finally {
        setLoading(false);
      }
    })();
  }, [session, entityId]);

  useEffect(() => {
    if (!session || !entityId || !detail) return;
    const base = { token: session.token, organizationId: session.organizationId };
    (async () => {
      try {
        if (tab === "impact" && !impact) {
          setImpact(
            await api<Impact>(
              `/api/v1/company-intelligence/entities/${entityId}/impact?max_depth=3`,
              base,
            ),
          );
        }
        if (tab === "process" && !process) {
          setProcess(
            await api<ProcessPage>(
              `/api/v1/company-intelligence/processes/${entityId}`,
              base,
            ),
          );
        }
        if (tab === "changes" && !changes) {
          setChanges(
            await api<ChangesView>(
              `/api/v1/company-intelligence/entities/${entityId}/changes`,
              base,
            ),
          );
        }
      } catch {
        // Cada pestaña degrada sola: el resumen sigue visible.
      }
    })();
  }, [session, entityId, tab, detail, impact, process, changes]);

  const edgeRow = (edge: Edge) => (
    <li key={edge.id} className="flex flex-wrap items-center gap-2 text-sm">
      <Link className="underline" to={`/company-intelligence/entity/${edge.from.id}`}>
        {edge.from.name}
      </Link>
      <Badge tone="neutral">{edge.relationship_type}</Badge>
      <Link className="underline" to={`/company-intelligence/entity/${edge.to.id}`}>
        {edge.to.name}
      </Link>
      <Badge tone={statusToneFor(edge.status)}>{statusLabelFor(edge.status)}</Badge>
      {edge.confidence !== null && (
        <span className="text-xs text-muted">
          confianza {Math.round(edge.confidence * 100)}%
        </span>
      )}
      {!edge.confirmed && (
        <span className="text-xs text-muted">no confirmada: impacto potencial</span>
      )}
    </li>
  );

  return (
    <CompanyIntelligenceLayout>
      {loading && (
        <Panel>
          <SkeletonBlock rows={5} />
        </Panel>
      )}
      <ErrorInline message={error} />

      {!loading && detail && (
        <>
          <PageHeader
            title={detail.entity.display_name}
            subtitle={`${entityTypeLabel(detail.entity.entity_type)} · ${detail.entity.domain}`}
          />
          <div className="mb-3 flex flex-wrap items-center gap-2">
            <Badge tone={statusToneFor(detail.entity.status)}>
              {statusLabelFor(detail.entity.status)}
            </Badge>
            {detail.entity.authority_level && (
              <Badge tone="info">Autoridad: {detail.entity.authority_level}</Badge>
            )}
            {detail.entity.confidence !== null && (
              <Badge tone="neutral">
                Confianza {Math.round(detail.entity.confidence * 100)}%
              </Badge>
            )}
            <span className="text-xs text-muted">
              Última observación {timeAgo(detail.entity.last_observed_at)}
            </span>
          </div>

          <PageTabs
            tabs={TABS}
            active={tab}
            onChange={(id) => setParams({ tab: id })}
            idPrefix="company-entity"
          />

          <div className="mt-4 space-y-4">
            {tab === "overview" && (
              <>
                {detail.entity.description && (
                  <Panel>
                    <PanelHeader title="Descripción" />
                    <p className="text-sm">{detail.entity.description}</p>
                  </Panel>
                )}
                {detail.entity.aliases.length > 0 && (
                  <Panel>
                    <PanelHeader title="Aliases" />
                    <div className="flex flex-wrap gap-2">
                      {detail.entity.aliases.map((alias) => (
                        <Badge key={alias} tone="neutral">
                          {alias}
                        </Badge>
                      ))}
                    </div>
                  </Panel>
                )}
                {detail.technical_mappings.length > 0 && (
                  <Panel>
                    <PanelHeader
                      title="Mapeos técnicos"
                      description="Concepto → representación física con sus valores"
                    />
                    <ul className="space-y-2 text-sm" data-testid="mapping-list">
                      {detail.technical_mappings.map((mapping) => (
                        <li key={mapping.id}>
                          <span className="font-medium">{mapping.target}</span>{" "}
                          <span className="text-muted">({mapping.target_type})</span>{" "}
                          {mapping.values.length > 0 && (
                            <span>valores: {mapping.values.join(", ")}</span>
                          )}{" "}
                          <Badge tone={statusToneFor(mapping.status)}>
                            {statusLabelFor(mapping.status)}
                          </Badge>
                        </li>
                      ))}
                    </ul>
                  </Panel>
                )}
                {detail.authority.length > 0 && (
                  <Panel>
                    <PanelHeader title="Fuentes y autoridad" />
                    <ul className="space-y-1 text-sm">
                      {detail.authority.map((item) => (
                        <li key={`${item.source_name}-${item.authority_level}`}>
                          {item.source_name} · {item.authority_level} ({item.source_type})
                        </li>
                      ))}
                    </ul>
                  </Panel>
                )}
                {detail.knowledge_gaps.length > 0 && (
                  <Panel>
                    <PanelHeader title="Conocimiento incompleto" />
                    <ul className="space-y-1 text-sm">
                      {detail.knowledge_gaps.map((gap) => (
                        <li key={gap.id}>
                          <Badge tone="warn">{gapLabel(gap.gap_kind)}</Badge>{" "}
                          {gap.detail}
                        </li>
                      ))}
                    </ul>
                  </Panel>
                )}
              </>
            )}

            {tab === "dependencies" && (
              <>
                <Panel>
                  <PanelHeader title="Relaciones entrantes" />
                  <ul className="space-y-2" data-testid="incoming-list">
                    {detail.incoming.map(edgeRow)}
                    {detail.incoming.length === 0 && (
                      <li className="text-sm text-muted">Sin relaciones entrantes.</li>
                    )}
                  </ul>
                </Panel>
                <Panel>
                  <PanelHeader title="Relaciones salientes" />
                  <ul className="space-y-2" data-testid="outgoing-list">
                    {detail.outgoing.map(edgeRow)}
                    {detail.outgoing.length === 0 && (
                      <li className="text-sm text-muted">Sin relaciones salientes.</li>
                    )}
                  </ul>
                </Panel>
                <Panel>
                  <PanelHeader title="Vecindad agrupada" />
                  <div className="space-y-2 text-sm">
                    {Object.entries(detail.related).map(([group, items]) => (
                      <div key={group}>
                        <p className="text-muted">{groupLabel(group)}</p>
                        <div className="flex flex-wrap gap-1">
                          {items.map((item) => (
                            <Link
                              key={item.id}
                              className="badge badge-muted"
                              to={`/company-intelligence/entity/${item.id}`}
                            >
                              {item.display_name}
                            </Link>
                          ))}
                        </div>
                      </div>
                    ))}
                  </div>
                </Panel>
              </>
            )}

            {tab === "impact" && (
              <Panel>
                <PanelHeader
                  title="¿Qué se afecta si esto cambia?"
                  description="Los caminos con relaciones no confirmadas se marcan como potenciales"
                />
                {!impact && <SkeletonBlock rows={3} />}
                {impact && (
                  <>
                    <div className="mb-3 flex flex-wrap gap-2 text-sm">
                      {Object.entries(impact.affected).map(([bucket, items]) => (
                        <Badge key={bucket} tone="neutral">
                          {groupLabel(bucket)} · {fmtNum(items.length)}
                        </Badge>
                      ))}
                    </div>
                    <ul className="space-y-2 text-sm" data-testid="impact-paths">
                      {impact.paths.map((path) => (
                        <li key={path.target_id}>
                          <Link
                            className="underline"
                            to={`/company-intelligence/entity/${path.target_id}`}
                          >
                            {path.target}
                          </Link>{" "}
                          <span className="text-muted">{path.hops} saltos</span>{" "}
                          <Badge tone={path.certainty === "will" ? "ok" : "warn"}>
                            {certaintyNote(path.certainty)}
                          </Badge>
                          <p className="text-xs text-muted">
                            {path.explanation
                              .map(
                                (step) =>
                                  `${step.from} ${step.relationship_type} ${step.to}`,
                              )
                              .join(" · ")}
                          </p>
                        </li>
                      ))}
                      {impact.paths.length === 0 && (
                        <li className="text-muted">Sin caminos registrados.</li>
                      )}
                    </ul>
                    {impact.truncated && (
                      <WarningInline message="Resultado truncado por límite de nodos." />
                    )}
                  </>
                )}
              </Panel>
            )}

            {tab === "process" && (
              <Panel>
                <PanelHeader title="Process Intelligence" />
                {!process && <SkeletonBlock rows={3} />}
                {process && (
                  <div className="space-y-3 text-sm">
                    <div>
                      <p className="text-muted">Diseñado documentado</p>
                      {process.designed?.steps?.length ? (
                        <p>{process.designed.steps.map((step) => step.name).join(" → ")}</p>
                      ) : (
                        <p className="text-muted">Sin proceso diseñado registrado.</p>
                      )}
                    </div>
                    <div>
                      <p className="text-muted">Observado</p>
                      {process.observed?.steps?.length ? (
                        <ul className="space-y-1">
                          {process.observed.steps.map((step) => (
                            <li key={step.name}>
                              {step.name} · {Math.round(step.frequency * 100)}% de{" "}
                              {process.observed?.runs_observed} corridas
                            </li>
                          ))}
                        </ul>
                      ) : (
                        <p className="text-muted">Sin corridas observadas.</p>
                      )}
                    </div>
                    {process.deviation.available && (
                      <div>
                        <p className="text-muted">Desviación</p>
                        <p data-testid="deviation-note">
                          Retrabajo en{" "}
                          {Math.round((process.deviation.rework_frequency || 0) * 100)}% de{" "}
                          {process.deviation.runs} corridas observadas.
                        </p>
                        <p className="text-xs text-muted">{process.deviation.note}</p>
                      </div>
                    )}
                    <div className="flex flex-wrap gap-2">
                      {process.systems.map((item) => (
                        <Badge key={item.id} tone="neutral">
                          Sistema: {item.name}
                        </Badge>
                      ))}
                      {process.agents.map((item) => (
                        <Badge key={item.id} tone="neutral">
                          Agente: {item.name}
                        </Badge>
                      ))}
                      {process.workflows.map((item) => (
                        <Badge key={item.id} tone="neutral">
                          Workflow: {item.name}
                        </Badge>
                      ))}
                    </div>
                  </div>
                )}
              </Panel>
            )}

            {tab === "memory" && (
              <Panel>
                <PanelHeader
                  title="Qué aprendió Zent"
                  description="Memoria operativa y hallazgos ligados a esta entidad"
                />
                <ul className="space-y-2 text-sm" data-testid="memory-list">
                  {detail.memory.map((record) => (
                    <li key={record.id}>
                      <span className="font-medium">{record.pattern_key}</span>{" "}
                      <Badge tone={statusToneFor(record.status)}>
                        {statusLabelFor(record.status)}
                      </Badge>
                      <p className="text-xs text-muted">
                        {record.title} · éxito {Math.round(record.success_rate * 100)}% ·{" "}
                        {record.support_count} observaciones
                      </p>
                    </li>
                  ))}
                  {detail.memory.length === 0 && (
                    <li className="text-muted">
                      Sin memoria operativa ligada todavía.
                    </li>
                  )}
                </ul>
              </Panel>
            )}

            {tab === "changes" && (
              <Panel>
                <PanelHeader title="¿Qué cambió?" />
                {!changes && <SkeletonBlock rows={3} />}
                {changes && (
                  <div className="space-y-3 text-sm">
                    <p className="text-muted">Comparado contra {changes.compared_to.slice(0, 10)}</p>
                    <div>
                      <p>Relaciones agregadas: {changes.relationships_added.length}</p>
                      <p>Relaciones removidas: {changes.relationships_removed.length}</p>
                    </div>
                    <ul className="space-y-1" data-testid="history-list">
                      {changes.history.slice(0, 10).map((item) => (
                        <li key={item.id}>
                          {item.relationship_type} · {statusLabelFor(item.status)} ·{" "}
                          <span className="text-muted">{timeAgo(item.created_at)}</span>
                        </li>
                      ))}
                    </ul>
                  </div>
                )}
              </Panel>
            )}
          </div>
        </>
      )}
    </CompanyIntelligenceLayout>
  );
}
