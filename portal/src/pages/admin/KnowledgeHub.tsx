import { BookOpen, Database, Warning } from "@phosphor-icons/react";
import { useEffect, useState } from "react";
import { platformApi } from "../../api";
import {
  EmptyState,
  ErrorInline,
  Metric,
  MetricGrid,
  PageHeader,
  Panel,
  PanelHeader,
  Skeleton,
} from "../../components/ui";
import { usePlatformAuth } from "../../platformAuth";

type Dash = { total_sources: number; total_documents: number; duplicates_removed: number; failed_refreshes_7d: number; open_gaps: number; sources_by_type: { source_type: string; count: number }[]; top_gaps: { query: string; occurrences: number }[] };

export default function AdminKnowledgeHubPage() {
  const { session } = usePlatformAuth();
  const [dash, setDash] = useState<Dash | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  async function load() {
    if (!session) return;
    setError("");
    try {
      const d = await platformApi<Dash>("/api/v1/platform/knowledge-hub/dashboard", { token: session.token });
      setDash(d);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Error");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    void load();
    const id = setInterval(() => void load(), 15000);
    return () => clearInterval(id);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [session]);

  const sources = dash?.sources_by_type ?? [];
  const gaps = dash?.top_gaps ?? [];

  return (
    <div className="space-y-6">
      <PageHeader title="Knowledge Hub" subtitle="Fuentes de conocimiento en todas las organizaciones: cobertura, deduplicación y huecos." />
      <ErrorInline message={error} />
      {loading ? (
        <div className="flex flex-col gap-3" aria-hidden>
          <Skeleton className="h-[86px] rounded-lg" />
          <Skeleton className="h-[220px] rounded-lg" />
        </div>
      ) : (
        <>
          <div className="grid grid-cols-1 gap-3 lg:grid-cols-[minmax(0,1fr)_minmax(0,2fr)]">
            <Metric
              label="Documentos"
              value={(dash?.total_documents ?? 0).toLocaleString()}
              hint="Total vectorizado en todas las organizaciones"
              icon={Database}
            />
            <MetricGrid cols={4} className="lg:grid-cols-4">
              <Metric label="Fuentes" value={(dash?.total_sources ?? 0).toLocaleString()} size="md" />
              <Metric
                label="Duplicados evitados"
                value={(dash?.duplicates_removed ?? 0).toLocaleString()}
                size="md"
                hint="Deduplicación activa"
              />
              <Metric
                label="Refrescos fallidos 7d"
                value={(dash?.failed_refreshes_7d ?? 0).toLocaleString()}
                size="md"
                tone={(dash?.failed_refreshes_7d ?? 0) > 0 ? "warn" : "default"}
              />
              <Metric
                label="Huecos abiertos"
                value={(dash?.open_gaps ?? 0).toLocaleString()}
                size="md"
                tone={(dash?.open_gaps ?? 0) > 0 ? "warn" : "default"}
              />
            </MetricGrid>
          </div>

          <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
            <Panel>
              <PanelHeader
                title={
                  <span className="flex items-center gap-2">
                    <BookOpen size={15} aria-hidden /> Fuentes por tipo
                  </span>
                }
                description="Cómo se reparte la cobertura entre conectores."
              />
              {sources.length === 0 ? (
                <EmptyState
                  compact
                  icon={BookOpen}
                  title="Sin fuentes conectadas"
                  body="Cuando una organización conecte su primera fuente, aparecerá acá con su tipo."
                />
              ) : (
                <ul className="divide-y divide-border-soft">
                  {sources.map((t) => (
                    <li key={t.source_type} className="flex items-center justify-between gap-3 px-4 py-2.5">
                      <span className="min-w-0 truncate text-[13px] text-text">{t.source_type}</span>
                      <span className="mono shrink-0 text-xs text-muted">{t.count.toLocaleString()}</span>
                    </li>
                  ))}
                </ul>
              )}
            </Panel>

            <Panel>
              <PanelHeader
                title={
                  <span className="flex items-center gap-2">
                    <Warning size={15} aria-hidden /> Huecos más frecuentes
                  </span>
                }
                description="Consultas sin cobertura, ordenadas por ocurrencias."
              />
              {gaps.length === 0 ? (
                <EmptyState
                  compact
                  icon={Warning}
                  title="Sin huecos abiertos"
                  body="No hay consultas sin cobertura en el periodo."
                />
              ) : (
                <ul className="divide-y divide-border-soft">
                  {gaps.map((g) => (
                    <li key={g.query} className="flex items-center justify-between gap-3 px-4 py-2.5">
                      <span className="min-w-0 truncate text-[13px] text-text" title={g.query}>{g.query}</span>
                      <span className="mono shrink-0 text-xs text-warn">×{g.occurrences}</span>
                    </li>
                  ))}
                </ul>
              )}
            </Panel>
          </div>
        </>
      )}
    </div>
  );
}
