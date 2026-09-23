import { useEffect, useState } from "react";
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
import { COPY, gapLabel, statusLabelFor, statusToneFor } from "./companyCopy";

type Gap = {
  id?: string;
  gap_kind: string;
  subject: string;
  detail: string;
  frequency?: number | null;
  observed_runs?: number | null;
  stage?: string;
  confidence?: number | null;
  origin?: string;
};

type Gaps = {
  items: Gap[];
  by_kind: Record<string, number>;
};

export default function CompanyKnowledgeGapsPage() {
  const { session } = useAuth();
  const [gaps, setGaps] = useState<Gaps | null>(null);
  const [filter, setFilter] = useState("");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  useEffect(() => {
    if (!session) return;
    (async () => {
      setLoading(true);
      setError("");
      try {
        setGaps(
          await api<Gaps>("/api/v1/company-intelligence/knowledge-gaps?limit=200", {
            token: session.token,
            organizationId: session.organizationId,
          }),
        );
      } catch (err) {
        setError(err instanceof Error ? err.message : "Error cargando huecos");
        setGaps(null);
      } finally {
        setLoading(false);
      }
    })();
  }, [session]);

  const items = (gaps?.items || []).filter(
    (gap) => !filter || gap.gap_kind === filter,
  );

  return (
    <CompanyIntelligenceLayout>
      <PageHeader
        title={COMPANY_HEADINGS.gaps}
        subtitle="Lo que Zent todavía no sabe: pasos sin documentar, conceptos sin fuente y relaciones obsoletas."
      />
      <ErrorInline message={error} />

      {loading && (
        <Panel>
          <SkeletonBlock rows={4} />
        </Panel>
      )}

      {!loading && gaps && (
        <div className="space-y-4">
          <Panel>
            <PanelHeader
              title="Resumen por tipo"
              actions={
                <Select
                  value={filter}
                  onChange={(event) => setFilter(event.target.value)}
                  aria-label="Filtrar por tipo de hueco"
                >
                  <option value="">Todos los tipos</option>
                  {Object.keys(gaps.by_kind).map((kind) => (
                    <option key={kind} value={kind}>
                      {gapLabel(kind)}
                    </option>
                  ))}
                </Select>
              }
            />
            <div className="flex flex-wrap gap-2">
              {Object.entries(gaps.by_kind).map(([kind, count]) => (
                <Badge key={kind} tone="warn">
                  {gapLabel(kind)} · {count}
                </Badge>
              ))}
              {Object.keys(gaps.by_kind).length === 0 && (
                <p className="text-sm text-muted">Sin huecos detectados.</p>
              )}
            </div>
          </Panel>

          {items.length === 0 ? (
            <Panel>
              <EmptyState
                title="Sin huecos con ese filtro"
                body="Probá con otro tipo o ejecutá descubrimiento para actualizar la foto."
              />
            </Panel>
          ) : (
            <Panel>
              <PanelHeader title="Detalle" />
              <ul className="space-y-3 text-sm" data-testid="gap-list">
                {items.map((gap, index) => (
                  <li key={gap.id || `${gap.gap_kind}-${gap.subject}-${index}`}>
                    <div className="flex flex-wrap items-center gap-2">
                      <Badge tone="warn">{gapLabel(gap.gap_kind)}</Badge>
                      <span className="font-medium">{gap.subject}</span>
                      {gap.stage && (
                        <Badge tone={statusToneFor(gap.stage)}>
                          {statusLabelFor(gap.stage)}
                        </Badge>
                      )}
                      <span className="text-xs text-muted">
                        origen: {gap.origin === "graph" ? "grafo" : "descubrimiento"}
                      </span>
                    </div>
                    <p className="text-muted">{gap.detail}</p>
                    {gap.frequency !== null && gap.frequency !== undefined && (
                      <p className="text-xs text-muted">
                        {Math.round(gap.frequency * 100)}% de{" "}
                        {gap.observed_runs} corridas observadas
                      </p>
                    )}
                  </li>
                ))}
              </ul>
            </Panel>
          )}
        </div>
      )}

      {!loading && !gaps && !error && (
        <Panel>
          <EmptyState title="Sin datos" body={COPY.empty} />
        </Panel>
      )}
    </CompanyIntelligenceLayout>
  );
}
