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
  SkeletonBlock,
} from "../../components/ui";
import { COMPANY_HEADINGS } from "../../lib/companyNav";
import { authorityLabel, COPY } from "./companyCopy";

type Source = {
  source_name: string;
  source_type: string;
  authority_level: string;
  priority: number;
};

type Entry = {
  concept_id: string;
  concept: string;
  domain: string;
  authoritative: Source[];
  primary: Source[];
  secondary: Source[];
  informational: Source[];
  sources: Source[];
  has_authority: boolean;
};

type Truth = {
  items: Entry[];
  conflicts: Array<{ id: string; subject: string; detail: string }>;
  concepts_without_authority: string[];
};

const LEVELS: Array<[keyof Pick<Entry, "authoritative" | "primary" | "secondary" | "informational">, string]> = [
  ["authoritative", "authoritative"],
  ["primary", "primary"],
  ["secondary", "secondary"],
  ["informational", "informational"],
];

export default function CompanySourceAuthorityPage() {
  const { session } = useAuth();
  const [truth, setTruth] = useState<Truth | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  useEffect(() => {
    if (!session) return;
    (async () => {
      setLoading(true);
      setError("");
      try {
        setTruth(
          await api<Truth>("/api/v1/company-intelligence/source-of-truth", {
            token: session.token,
            organizationId: session.organizationId,
          }),
        );
      } catch (err) {
        setError(err instanceof Error ? err.message : "Error cargando autoridad");
        setTruth(null);
      } finally {
        setLoading(false);
      }
    })();
  }, [session]);

  return (
    <CompanyIntelligenceLayout>
      <PageHeader
        title={COMPANY_HEADINGS.authority}
        subtitle="Qué fuente manda sobre cada concepto, por dominio y por nivel de autoridad."
      />
      <ErrorInline message={error} />
      {loading && (
        <Panel>
          <SkeletonBlock rows={4} />
        </Panel>
      )}

      {!loading && truth && truth.items.length === 0 && (
        <Panel>
          <EmptyState title="Sin conceptos" body={COPY.empty} />
        </Panel>
      )}

      {!loading && truth && truth.items.length > 0 && (
        <div className="space-y-4">
          {truth.items.map((entry) => (
            <Panel key={entry.concept_id} data-testid="authority-entry">
              <PanelHeader
                title={entry.concept}
                description={`Dominio ${entry.domain}`}
                actions={
                  <Link
                    className="text-sm underline"
                    to={`/company-intelligence/entity/${entry.concept_id}`}
                  >
                    Ver concepto
                  </Link>
                }
              />
              {!entry.has_authority && (
                <p className="mb-2 text-sm">
                  <Badge tone="warn">Sin fuente autoritativa</Badge> Es un hueco de
                  conocimiento: conviene declarar cuál manda.
                </p>
              )}
              <div className="space-y-2 text-sm">
                {LEVELS.map(([key, level]) => {
                  const sources = entry[key] as Source[];
                  if (!sources || sources.length === 0) return null;
                  return (
                    <div key={level} className="flex flex-wrap items-center gap-2">
                      <Badge tone={level === "authoritative" ? "ok" : "neutral"}>
                        {authorityLabel(level)}
                      </Badge>
                      {sources.map((source) => (
                        <span key={source.source_name}>
                          {source.source_name}{" "}
                          <span className="text-xs text-muted">({source.source_type})</span>
                        </span>
                      ))}
                    </div>
                  );
                })}
                {entry.sources.length === 0 && (
                  <p className="text-muted">Sin fuentes configuradas.</p>
                )}
              </div>
            </Panel>
          ))}

          {truth.conflicts.length > 0 && (
            <Panel>
              <PanelHeader
                title="Conflictos entre fuentes"
                description="Detectados sobre el Claim Ledger, no en un sistema aparte"
              />
              <ul className="space-y-2 text-sm" data-testid="conflict-list">
                {truth.conflicts.map((conflict) => (
                  <li key={conflict.id}>
                    <Badge tone="danger">Conflicto</Badge> {conflict.subject}
                    <p className="text-xs text-muted">{conflict.detail}</p>
                  </li>
                ))}
              </ul>
            </Panel>
          )}
        </div>
      )}
    </CompanyIntelligenceLayout>
  );
}
