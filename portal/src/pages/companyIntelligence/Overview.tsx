import { WarningOctagon } from "@phosphor-icons/react";
import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../../api";
import { useAuth } from "../../auth";
import { CompanyIntelligenceLayout } from "../../components/CompanyIntelligenceLayout";
import {
  Badge,
  EmptyState,
  ErrorInline,
  Metric,
  MetricGrid,
  PageHeader,
  Panel,
  PanelHeader,
  SkeletonBlock,
} from "../../components/ui";
import { COMPANY_HEADINGS } from "../../lib/companyNav";
import { fmtNum, timeAgo } from "../../lib/format";
import { COPY, gapLabel, statusLabelFor, statusToneFor } from "./companyCopy";

type Overview = {
  entities: {
    total: number;
    by_status: Record<string, number>;
    by_type: Record<string, number>;
    confirmed: number;
    discovered: number;
    contradicted: number;
    stale: number;
  };
  relationships: {
    total: number;
    confirmed: number;
    by_status: Record<string, number>;
  };
  knowledge_gaps: { total: number; by_kind: Record<string, number> };
  potential_risks: number;
  coverage: Record<string, number>;
  discovery: { available?: boolean; total?: number; by_kind?: Record<string, number> };
  as_of: string;
};

type Risk = {
  risk_kind: string;
  level: string;
  entity_id: string;
  entity: string;
  entity_type: string;
  detail: string;
};

type Changes = {
  items: Array<{
    kind: string;
    at: string;
    title: string;
    entity_id?: string;
    status?: string;
  }>;
};

export default function CompanyOverviewPage() {
  const { session } = useAuth();
  const [overview, setOverview] = useState<Overview | null>(null);
  const [risks, setRisks] = useState<Risk[]>([]);
  const [changes, setChanges] = useState<Changes["items"]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  useEffect(() => {
    if (!session) return;
    (async () => {
      setLoading(true);
      setError("");
      try {
        const [ov, rk, ch] = await Promise.all([
          api<Overview>("/api/v1/company-intelligence/overview", {
            token: session.token,
            organizationId: session.organizationId,
          }),
          api<{ items: Risk[] }>("/api/v1/company-intelligence/risks?limit=5", {
            token: session.token,
            organizationId: session.organizationId,
          }).catch(() => ({ items: [] as Risk[] })),
          api<Changes>("/api/v1/company-intelligence/changes?limit=6", {
            token: session.token,
            organizationId: session.organizationId,
          }).catch(() => ({ items: [] })),
        ]);
        setOverview(ov);
        setRisks(rk.items || []);
        setChanges(ch.items || []);
      } catch (err) {
        setError(err instanceof Error ? err.message : "Error cargando la empresa");
      } finally {
        setLoading(false);
      }
    })();
  }, [session]);

  const empty = !loading && overview !== null && overview.entities.total === 0;

  return (
    <CompanyIntelligenceLayout>
      <PageHeader title={COMPANY_HEADINGS.overview} subtitle={COPY.subtitle} />

      <ErrorInline message={error} />

      {loading && (
        <Panel>
          <SkeletonBlock rows={4} />
        </Panel>
      )}

      {empty && (
        <Panel>
          <EmptyState title="Sin entidades todavía" body={COPY.empty} />
        </Panel>
      )}

      {!loading && overview && !empty && (
        <div className="space-y-4">
          <MetricGrid cols={4}>
            <Metric label="Conceptos" value={fmtNum(overview.coverage.concepts || 0)} />
            <Metric label="Procesos" value={fmtNum(overview.coverage.processes || 0)} />
            <Metric label="Sistemas" value={fmtNum(overview.coverage.systems || 0)} />
            <Metric label="Datasets" value={fmtNum(overview.coverage.datasets || 0)} />
            <Metric label="Tablas" value={fmtNum(overview.coverage.tables || 0)} />
            <Metric label="Reglas" value={fmtNum(overview.coverage.rules || 0)} />
            <Metric
              label="Relaciones"
              value={fmtNum(overview.relationships.total)}
            />
            <Metric
              label="Huecos de conocimiento"
              value={fmtNum(overview.knowledge_gaps.total)}
            />
          </MetricGrid>

          <div className="grid gap-4 lg:grid-cols-2">
            <Panel>
              <PanelHeader title="Estado del grafo" />
              <div className="flex flex-wrap gap-2">
                {Object.entries(overview.entities.by_status)
                  .sort((a, b) => b[1] - a[1])
                  .map(([status, count]) => (
                    <Badge key={status} tone={statusToneFor(status)}>
                      {statusLabelFor(status)} · {fmtNum(count)}
                    </Badge>
                  ))}
              </div>
              <p className="mt-3 text-sm text-muted">
                {fmtNum(overview.relationships.confirmed)} de{" "}
                {fmtNum(overview.relationships.total)} relaciones están confirmadas.
              </p>
              <div className="mt-2">
                <Link className="text-sm underline" to="/company-intelligence/relationships">
                  Ver relaciones
                </Link>
              </div>
            </Panel>

            <Panel>
              <PanelHeader title="Conocimiento incompleto" />
              {overview.knowledge_gaps.total === 0 ? (
                <p className="text-sm text-muted">Sin huecos detectados.</p>
              ) : (
                <ul className="space-y-1 text-sm">
                  {Object.entries(overview.knowledge_gaps.by_kind).map(
                    ([kind, count]) => (
                      <li key={kind} className="flex justify-between gap-2">
                        <span>{gapLabel(kind)}</span>
                        <span className="text-muted">{fmtNum(count)}</span>
                      </li>
                    ),
                  )}
                </ul>
              )}
              <div className="mt-3">
                <Link className="text-sm underline" to="/company-intelligence/gaps">
                  Ver huecos
                </Link>
              </div>
            </Panel>
          </div>

          {risks.length > 0 && (
            <Panel>
              <PanelHeader
                title="Riesgos potenciales"
                description="Candidatos detectados por el grafo, nunca riesgos definitivos"
              />
              <ul className="space-y-2 text-sm" data-testid="risk-list">
                {risks.map((risk) => (
                  <li key={`${risk.risk_kind}-${risk.entity_id}`} className="flex gap-2">
                    <WarningOctagon size={16} aria-hidden className="mt-0.5 shrink-0" />
                    <span>
                      {risk.detail}{" "}
                      <Badge tone="warn">Potencial</Badge>
                    </span>
                  </li>
                ))}
              </ul>
            </Panel>
          )}

          {changes.length > 0 && (
            <Panel>
              <PanelHeader title="Últimos cambios" />
              <ul className="space-y-1 text-sm" data-testid="changes-list">
                {changes.map((change) => (
                  <li key={`${change.kind}-${change.at}-${change.title}`}>
                    <span className="text-muted">{timeAgo(change.at)}</span>{" "}
                    {change.entity_id ? (
                      <Link
                        className="underline"
                        to={`/company-intelligence/entity/${change.entity_id}`}
                      >
                        {change.title}
                      </Link>
                    ) : (
                      change.title
                    )}
                  </li>
                ))}
              </ul>
            </Panel>
          )}

          <p className="text-xs text-faint">
            Datos al {new Date(overview.as_of).toLocaleString("es-PE")}. Todo número
            proviene del backend.
          </p>
        </div>
      )}
    </CompanyIntelligenceLayout>
  );
}
