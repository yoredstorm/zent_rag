import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../../api";
import { useAuth } from "../../auth";
import { CompanyIntelligenceLayout } from "../../components/CompanyIntelligenceLayout";
import {
  Badge,
  EmptyState,
  ErrorInline,
  PageHeader,
  Panel,
  PanelHeader,
  Select,
  SkeletonBlock,
} from "../../components/ui";
import { COMPANY_HEADINGS } from "../../lib/companyNav";
import { fmtDateTime } from "../../lib/format";
import { changeLabel, COPY, statusLabelFor, statusToneFor } from "./companyCopy";

type Change = {
  kind: string;
  at: string;
  title: string;
  entity_id?: string;
  candidate_id?: string;
  status?: string;
  detail?: string;
  confidence?: number;
};

type Changes = {
  items: Change[];
  since: string;
};

const RANGES: Array<[string, number]> = [
  ["7 días", 7],
  ["30 días", 30],
  ["90 días", 90],
  ["1 año", 365],
];

export default function CompanyChangesPage() {
  const { session } = useAuth();
  const [changes, setChanges] = useState<Changes | null>(null);
  const [days, setDays] = useState(30);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  useEffect(() => {
    if (!session) return;
    (async () => {
      setLoading(true);
      setError("");
      try {
        const since = new Date(Date.now() - days * 86400000).toISOString();
        setChanges(
          await api<Changes>(
            `/api/v1/company-intelligence/changes?limit=200&since=${encodeURIComponent(since)}`,
            { token: session.token, organizationId: session.organizationId },
          ),
        );
      } catch (err) {
        setError(err instanceof Error ? err.message : "Error cargando cambios");
        setChanges(null);
      } finally {
        setLoading(false);
      }
    })();
  }, [session, days]);

  return (
    <CompanyIntelligenceLayout>
      <PageHeader
        title={COMPANY_HEADINGS.changes}
        subtitle="Qué cambió en la empresa, con la vigencia temporal de cada relación."
      />
      <ErrorInline message={error} />

      <div className="mb-3 flex items-end gap-2">
        <label className="text-sm">
          <span className="mr-2 text-muted">Período</span>
          <Select
            value={String(days)}
            onChange={(event) => setDays(Number(event.target.value))}
            aria-label="Período"
          >
            {RANGES.map(([label, value]) => (
              <option key={value} value={value}>
                {label}
              </option>
            ))}
          </Select>
        </label>
      </div>

      {loading && (
        <Panel>
          <SkeletonBlock rows={4} />
        </Panel>
      )}

      {!loading && changes && changes.items.length === 0 && (
        <Panel>
          <EmptyState
            title="Sin cambios en el período"
            body="Ampliá el rango o ejecutá descubrimiento para registrar novedades."
          />
        </Panel>
      )}

      {!loading && changes && changes.items.length > 0 && (
        <Panel>
          <PanelHeader
            title="Timeline"
            description={`Desde ${new Date(changes.since).toLocaleDateString("es-PE")}`}
          />
          <ol className="space-y-3 text-sm" data-testid="changes-timeline">
            {changes.items.map((change, index) => (
              <li
                key={`${change.kind}-${change.at}-${index}`}
                className="border-l border-border pl-3"
              >
                <div className="flex flex-wrap items-center gap-2">
                  <Badge tone="neutral">{changeLabel(change.kind)}</Badge>
                  {change.entity_id ? (
                    <Link
                      className="underline"
                      to={`/company-intelligence/entity/${change.entity_id}`}
                    >
                      {change.title}
                    </Link>
                  ) : (
                    <span className="font-medium">{change.title}</span>
                  )}
                  {change.status && (
                    <Badge tone={statusToneFor(change.status)}>
                      {statusLabelFor(change.status)}
                    </Badge>
                  )}
                </div>
                <p className="text-xs text-muted">{fmtDateTime(change.at)}</p>
                {change.detail && (
                  <p className="text-xs text-muted">{change.detail}</p>
                )}
              </li>
            ))}
          </ol>
        </Panel>
      )}

      {!loading && !changes && !error && (
        <Panel>
          <EmptyState title="Sin datos" body={COPY.empty} />
        </Panel>
      )}
    </CompanyIntelligenceLayout>
  );
}
