import {
  Binoculars,
  CaretRight,
  Database,
  Gauge,
  Tag,
  WarningCircle,
} from "@phosphor-icons/react";
import { useCallback, useEffect, useState } from "react";
import { api } from "../../api";
import { useAuth } from "../../auth";
import {
  Badge,
  Button,
  ButtonLink,
  EmptyState,
  ErrorInline,
  Metric,
  MetricGrid,
  PageHeader,
  Panel,
  PanelHeader,
  Progress,
  Skeleton,
  StatusBadge,
} from "../../components/ui";
import { KnowledgeLayout } from "../../components/KnowledgeLayout";
import { KNOWLEDGE_HEADINGS } from "../../lib/knowledgeNav";
import { fmtDateTime } from "../../lib/format";

type CatalogSource = {
  id: string;
  connector_id: string;
  engine: string;
  phase: string;
  last_scan_at: string | null;
  scan_error: string | null;
  content_signature: string | null;
};

type Readiness = {
  overall: number;
  schema_coverage: number;
  relationship_coverage: number;
  description_coverage: number;
  semantic_mapping_coverage: number;
  metric_coverage: number;
  glossary_coverage: number;
  freshness: number;
  data_quality: number;
  unknown_code_count: number;
  pending_review_count: number;
};

const COVERAGE: { key: keyof Readiness; label: string }[] = [
  { key: "schema_coverage", label: "Esquema" },
  { key: "relationship_coverage", label: "Relaciones" },
  { key: "description_coverage", label: "Descripciones" },
  { key: "semantic_mapping_coverage", label: "Semántico" },
  { key: "glossary_coverage", label: "Glosario" },
  { key: "metric_coverage", label: "Métricas" },
  { key: "freshness", label: "Frescura" },
  { key: "data_quality", label: "Calidad" },
];

/** Fase del discovery traducida a estado visible. */
function PhaseBadge({ phase }: { phase: string }) {
  switch (phase) {
    case "COMPLETED":
      return <StatusBadge status="completed" />;
    case "PARTIAL":
      return <StatusBadge status="partial" />;
    case "FAILED":
      return <StatusBadge status="failed" />;
    case "CANCELLED":
      return <StatusBadge status="canceled" />;
    case "QUEUED":
      return <StatusBadge status="queued" />;
    case "WAITING_REVIEW":
      return (
        <Badge tone="warn" icon={WarningCircle}>
          Esperando revisión
        </Badge>
      );
    case "SCANNING":
      return (
        <Badge tone="accent" dot>
          Escaneando
        </Badge>
      );
    case "PROFILING":
      return (
        <Badge tone="accent" dot>
          Perfilando
        </Badge>
      );
    case "INFERRING":
      return (
        <Badge tone="accent" dot>
          Infiriendo
        </Badge>
      );
    default:
      return <Badge tone="neutral">{phase}</Badge>;
  }
}

export default function KnowledgeCatalogPage() {
  const { session } = useAuth();
  const [sources, setSources] = useState<CatalogSource[]>([]);
  const [readiness, setReadiness] = useState<Record<string, Readiness>>({});
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [scanning, setScanning] = useState("");

  const load = useCallback(() => {
    if (!session) return;
    setLoading(true);
    api<CatalogSource[]>("/api/v1/catalog/sources", {
      token: session?.token,
      organizationId: session?.organizationId,
    })
      .then(async (rows) => {
        setSources(rows);
        const ready: Record<string, Readiness> = {};
        await Promise.all(
          rows.map(async (s) => {
            try {
              ready[s.id] = await api<Readiness>(`/api/v1/catalog/sources/${s.id}/readiness`, {
                token: session?.token,
                organizationId: session?.organizationId,
              });
            } catch {
              /* sin readiness */
            }
          })
        );
        setReadiness(ready);
      })
      .catch((e) => setError(String(e)))
      .finally(() => setLoading(false));
  }, [session]);

  useEffect(() => load(), [load]);

  const startScan = async (sourceId: string) => {
    setScanning(sourceId);
    try {
      await api<{ job_id: string }>(`/api/v1/catalog/sources/${sourceId}/rescan`, {
        method: "POST",
        token: session?.token,
        organizationId: session?.organizationId,
        body: JSON.stringify({}),
      });
      setScanning("");
      load();
    } catch (e) {
      setError(String(e));
      setScanning("");
    }
  };

  const measured = sources
    .map((s) => readiness[s.id])
    .filter((r): r is Readiness => Boolean(r));
  const avgReadiness = measured.length
    ? Math.round(measured.reduce((acc, r) => acc + r.overall, 0) / measured.length)
    : null;
  const pendingReview = measured.reduce((acc, r) => acc + r.pending_review_count, 0);
  const unknownCodes = measured.reduce((acc, r) => acc + r.unknown_code_count, 0);

  return (
    <KnowledgeLayout>
      <PageHeader
        title={KNOWLEDGE_HEADINGS.catalog}
        subtitle="Metadata y catálogo semántico descubiertos de forma autónoma. Cada fuente muestra qué tan lista está para responder."
      />

      {error && <ErrorInline message={error} />}

      {loading ? (
        <div className="flex flex-col gap-4" aria-hidden>
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-4">
            {Array.from({ length: 4 }).map((_, i) => (
              <Skeleton key={i} className="h-[86px] rounded-lg" />
            ))}
          </div>
          <Skeleton className="h-[232px] rounded-lg" />
        </div>
      ) : sources.length === 0 ? (
        <EmptyState
          icon={Binoculars}
          title="Todavía no hay catálogo"
          body="Conectá una fuente SQL y ejecutá la primera exploración. Zent descubre tablas, columnas y relaciones, y las deja listas para revisar."
          hint="La exploración también se puede relanzar por fuente cuando cambia el esquema."
          action={
            <ButtonLink to="/knowledge/add" variant="primary" leadingIcon={Database}>
              Conectar mis datos
            </ButtonLink>
          }
        />
      ) : (
        <div className="flex flex-col gap-6">
          <MetricGrid cols={4}>
            <Metric
              label="Readiness promedio"
              icon={Gauge}
              tone="accent"
              value={avgReadiness === null ? "—" : `${avgReadiness}%`}
              hint={
                measured.length
                  ? `${measured.length} de ${sources.length} fuentes medidas`
                  : "Sin mediciones todavía"
              }
            />
            <Metric
              label="Fuentes"
              icon={Database}
              value={sources.length}
              hint="Conectores SQL descubiertos"
            />
            <Metric
              label="En revisión"
              icon={Binoculars}
              tone={pendingReview > 0 ? "warn" : "default"}
              value={pendingReview}
              hint="Sugerencias pendientes de aprobación"
            />
            <Metric
              label="Códigos sin documentar"
              icon={Tag}
              tone={unknownCodes > 0 ? "warn" : "default"}
              value={unknownCodes}
              hint="Valores de enum sin significado"
            />
          </MetricGrid>

          <div className="flex flex-col gap-3">
            {sources.map((s) => {
              const r = readiness[s.id];
              return (
                <Panel key={s.id}>
                  <PanelHeader
                    title={s.engine}
                    description={
                      <>
                        Último scan:{" "}
                        {s.last_scan_at ? fmtDateTime(s.last_scan_at) : "nunca ejecutado"}
                      </>
                    }
                    actions={
                      <>
                        {r && r.pending_review_count > 0 && (
                          <Badge tone="warn" icon={WarningCircle}>
                            {r.pending_review_count} en revisión
                          </Badge>
                        )}
                        <PhaseBadge phase={s.phase} />
                        <Button
                          size="sm"
                          variant="secondary"
                          leadingIcon={CaretRight}
                          loading={scanning === s.id}
                          onClick={() => startScan(s.id)}
                        >
                          Volver a escanear
                        </Button>
                      </>
                    }
                  />

                  {s.scan_error && (
                    <div className="px-4 pt-3">
                      <ErrorInline
                        message={`El último scan reportó un error: ${s.scan_error}`}
                        className="mb-0"
                      />
                    </div>
                  )}

                  {r && (
                    <div className="flex flex-col gap-5 p-4 lg:flex-row lg:items-start">
                      <div className="lg:w-[228px] lg:shrink-0">
                        <p className="eyebrow">Readiness general</p>
                        <p className="stat-value mt-1.5">
                          {Math.round(r.overall)}
                          <span className="text-base font-medium text-muted">%</span>
                        </p>
                        <Progress
                          value={r.overall}
                          tone={r.overall >= 80 ? "ok" : r.overall >= 50 ? "accent" : "warn"}
                          className="mt-3"
                        />
                        <p className="mt-3 text-xs leading-relaxed text-muted">
                          Cuánto del esquema, las relaciones y el vocabulario ya está
                          confirmado por una persona.
                        </p>
                      </div>

                      <dl className="grid min-w-0 flex-1 grid-cols-2 gap-x-6 gap-y-3.5 sm:grid-cols-4">
                        {COVERAGE.map(({ key, label }) => (
                          <div key={key} className="min-w-0">
                            <dt className="eyebrow truncate">{label}</dt>
                            <dd className="mono mt-0.5 text-sm text-text">
                              {Math.round(r[key])}%
                            </dd>
                          </div>
                        ))}
                        <div className="min-w-0">
                          <dt className="eyebrow truncate">Códigos sin doc</dt>
                          <dd className="mono mt-0.5 text-sm text-text">
                            {r.unknown_code_count}
                          </dd>
                        </div>
                        <div className="min-w-0">
                          <dt className="eyebrow truncate">En revisión</dt>
                          <dd className="mono mt-0.5 text-sm text-text">
                            {r.pending_review_count}
                          </dd>
                        </div>
                      </dl>
                    </div>
                  )}
                </Panel>
              );
            })}
          </div>
        </div>
      )}
    </KnowledgeLayout>
  );
}
