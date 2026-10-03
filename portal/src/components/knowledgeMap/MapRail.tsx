// =============================================================================
// MapRail — el panel de inteligencia del Knowledge Map
// =============================================================================
// Knowledge Health, coverage real, evolución 7d, aprendizaje reciente y
// vacíos. Cada número sale de /health, /quality, /delta, /gaps y /domains.
// =============================================================================
import { useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { ChartLineUp, Heartbeat, Sparkle, Target } from "@phosphor-icons/react";

import {
  fetchKnowledgeDelta,
  fetchKnowledgeGaps,
  fetchKnowledgeHealth,
  fetchKnowledgeQuality,
  type KnowledgeDelta,
  type KnowledgeDomain,
  type KnowledgeGap,
  type KnowledgeHealth,
  type QualityReport,
} from "../../lib/knowledgeModel";
import { interpretHealth } from "../../lib/knowledgeLanguage";
import { timeAgo } from "../../lib/format";
import { Skeleton, cn } from "../ui";
import { HealthIndicator } from "../knowledge/badges";
import { domainCoverage } from "./mapInsights";

const ISSUE_LABELS: Record<string, { label: string; href: string }> = {
  conflict: { label: "Conflictos", href: "/knowledge/health?tab=conflicts" },
  orphan: { label: "Entidades aisladas", href: "/knowledge/health?tab=issues" },
  stale: { label: "Conocimiento vencido", href: "/knowledge/health?tab=issues" },
  unsupported: { label: "Hechos sin evidencia", href: "/knowledge/health?tab=issues" },
  low_confidence: { label: "Baja confianza", href: "/knowledge/health?tab=issues" },
  missing_description: { label: "Sin descripción", href: "/knowledge/health?tab=issues" },
};

const EVOLUTION_ROWS: Array<{ key: string; label: string }> = [
  { key: "entities", label: "conceptos" },
  { key: "facts", label: "hechos" },
  { key: "relationships", label: "relaciones" },
  { key: "rules", label: "reglas" },
  { key: "evidence", label: "evidencias" },
];

export function MapRail({
  domains,
  onSelectDomain,
  onSelectObject,
}: {
  domains: KnowledgeDomain[];
  onSelectDomain: (domain: string) => void;
  onSelectObject: (objectId: string) => void;
}) {
  const [health, setHealth] = useState<KnowledgeHealth | null>(null);
  const [quality, setQuality] = useState<QualityReport | null>(null);
  const [delta, setDelta] = useState<KnowledgeDelta | null>(null);
  const [gaps, setGaps] = useState<KnowledgeGap[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;
    void Promise.allSettled([
      fetchKnowledgeHealth(),
      fetchKnowledgeQuality(20),
      fetchKnowledgeDelta({ window: "7d" }),
      fetchKnowledgeGaps({ status: "open", limit: 6 }),
    ]).then(([healthResult, qualityResult, deltaResult, gapsResult]) => {
      if (cancelled) return;
      if (healthResult.status === "fulfilled") setHealth(healthResult.value);
      if (qualityResult.status === "fulfilled") setQuality(qualityResult.value);
      if (deltaResult.status === "fulfilled") setDelta(deltaResult.value);
      if (gapsResult.status === "fulfilled") setGaps(gapsResult.value.gaps);
      setLoading(false);
    });
    return () => {
      cancelled = true;
    };
  }, []);

  const issueCounts = useMemo(() => {
    if (!quality) return [];
    return quality.issues
      .filter((issue) => ISSUE_LABELS[issue.kind])
      .map((issue) => ({
        kind: issue.kind,
        count: issue.count,
        severity: issue.severity,
        ...ISSUE_LABELS[issue.kind],
      }));
  }, [quality]);

  const coverageDomains = useMemo(
    () =>
      domains
        .filter((domain) => domain.objects > 0)
        .sort((a, b) => b.objects - a.objects)
        .slice(0, 8),
    [domains]
  );

  const timelineMax = useMemo(() => {
    if (!delta) return 1;
    return Math.max(
      1,
      ...delta.timeline.map(
        (point) => point.objects + point.facts + point.relationships
      )
    );
  }, [delta]);

  if (loading) {
    return (
      <aside className="km-rail" aria-busy="true">
        <Skeleton className="h-[180px] rounded-lg" />
        <Skeleton className="h-[220px] rounded-lg" />
        <Skeleton className="h-[200px] rounded-lg" />
      </aside>
    );
  }

  return (
    <aside className="km-rail" data-testid="knowledge-map-rail">
      <section className="panel km-rail-panel">
        <header className="panel-header py-2.5">
          <h2 className="text-h3 flex items-center gap-2">
            <Heartbeat size={14} className="text-accent" aria-hidden />
            Knowledge Health
          </h2>
          <Link to="/knowledge/health" className="text-[11px] text-accent hover:underline">
            Ver centro
          </Link>
        </header>
        <div className="panel-body flex flex-col gap-3">
          {health && (
            <>
              <div className="flex items-center gap-3">
                <HealthIndicator value={health.overall} size={62} />
                <div className="min-w-0">
                  <p className="text-[12px] leading-relaxed text-text">
                    {interpretHealth(health)}
                  </p>
                  <p className="mt-0.5 text-[11px] text-faint">
                    {health.measured_dimensions} de {health.total_dimensions}{" "}
                    dimensiones medidas
                  </p>
                </div>
              </div>
              <ul className="km-rail-dims">
                {health.dimensions
                  .filter((dimension) => dimension.measured && dimension.score != null)
                  .slice(0, 5)
                  .map((dimension) => (
                    <li key={dimension.key}>
                      <span className="truncate text-[11px] text-muted">
                        {dimension.label}
                      </span>
                      <span
                        className={cn(
                          "mono text-[11px] tabular-nums",
                          dimension.score! >= 75
                            ? "text-ok"
                            : dimension.score! >= 50
                              ? "text-warn"
                              : "text-danger"
                        )}
                      >
                        {Math.round(dimension.score!)}
                      </span>
                    </li>
                  ))}
              </ul>
            </>
          )}
          {issueCounts.length > 0 && (
            <ul className="km-rail-issues">
              {issueCounts.map((issue) => (
                <li key={issue.kind}>
                  <Link to={issue.href} className="flex items-center justify-between gap-2">
                    <span className="truncate text-[11px] text-muted">
                      {issue.label}
                    </span>
                    <span
                      className={cn(
                        "mono text-[11px] tabular-nums",
                        issue.severity === "high" ? "text-danger" : "text-warn"
                      )}
                    >
                      {issue.count}
                    </span>
                  </Link>
                </li>
              ))}
            </ul>
          )}
          {quality && quality.issues.some((issue) => issue.kind === "orphan") && (
            <p className="text-[11px] leading-relaxed text-faint">
              ZENT conoce esas entidades pero todavía no entiende bien cómo se
              relacionan con el resto del negocio.
            </p>
          )}
        </div>
      </section>

      <section className="panel km-rail-panel">
        <header className="panel-header py-2.5">
          <h2 className="text-h3 flex items-center gap-2">
            <Target size={14} className="text-accent" aria-hidden />
            Cobertura
          </h2>
        </header>
        <div className="panel-body flex flex-col gap-2.5">
          {coverageDomains.length === 0 ? (
            <p className="text-[12px] text-muted">Sin dominios con conocimiento.</p>
          ) : (
            coverageDomains.map((domain) => {
              const coverage = domainCoverage(domain);
              return (
                <button
                  key={domain.name}
                  type="button"
                  className="km-coverage"
                  title={coverage.formula}
                  onClick={() => onSelectDomain(domain.name)}
                >
                  <span className="flex items-center justify-between gap-2">
                    <span className="min-w-0 truncate text-[12px] text-text">
                      {domain.name}
                    </span>
                    <span className="mono text-[11px] tabular-nums text-muted">
                      {coverage.label}
                    </span>
                  </span>
                  <span className="km-coverage-bar" aria-hidden>
                    <span
                      className={cn(
                        coverage.pct >= 70
                          ? "bg-ok"
                          : coverage.pct >= 40
                            ? "bg-warn"
                            : "bg-danger"
                      )}
                      style={{ width: `${Math.max(3, coverage.pct)}%` }}
                    />
                  </span>
                </button>
              );
            })
          )}
          <p className="text-[10px] leading-relaxed text-faint">
            Cobertura = objetos verificados sobre objetos de negocio del dominio.
          </p>
        </div>
      </section>

      <section className="panel km-rail-panel">
        <header className="panel-header py-2.5">
          <h2 className="text-h3 flex items-center gap-2">
            <ChartLineUp size={14} className="text-accent" aria-hidden />
            Evolución 7 días
          </h2>
        </header>
        <div className="panel-body flex flex-col gap-2.5">
          {delta ? (
            <>
              <ul className="km-rail-evolution">
                {EVOLUTION_ROWS.map((row) => {
                  const value = delta.totals[row.key as keyof typeof delta.totals] ?? 0;
                  return (
                    <li key={row.key}>
                      <span className="text-[11px] text-muted">{row.label}</span>
                      <span className="mono text-[12px] tabular-nums text-accent">
                        {value > 0 ? "+" : ""}
                        {Number(value).toLocaleString("es-PE")}
                      </span>
                    </li>
                  );
                })}
                <li>
                  <span className="text-[11px] text-muted">conflictos resueltos</span>
                  <span className="mono text-[12px] tabular-nums text-ok">
                    +{delta.totals.conflicts_resolved}
                  </span>
                </li>
              </ul>
              {delta.timeline.length > 0 && (
                <svg
                  viewBox={`0 0 ${Math.max(delta.timeline.length * 10, 100)} 30`}
                  className="h-[48px] w-full"
                  preserveAspectRatio="none"
                  role="img"
                  aria-label="Ritmo de aprendizaje de los últimos 7 días"
                >
                  {delta.timeline.map((point, index) => {
                    const total = point.objects + point.facts + point.relationships;
                    const height = (total / timelineMax) * 24;
                    return (
                      <rect
                        key={point.bucket ?? index}
                        x={index * 10 + 1}
                        y={26 - height}
                        width={8}
                        height={Math.max(1, height)}
                        rx={1.5}
                        className="km-timeline-bar"
                      >
                        <title>{`${total} cambios`}</title>
                      </rect>
                    );
                  })}
                </svg>
              )}
            </>
          ) : (
            <p className="text-[12px] text-muted">Sin datos de evolución.</p>
          )}
        </div>
      </section>

      <section className="panel km-rail-panel">
        <header className="panel-header py-2.5">
          <h2 className="text-h3 flex items-center gap-2">
            <Sparkle size={14} className="text-accent" aria-hidden />
            Aprendido recientemente
          </h2>
        </header>
        <div className="panel-body">
          {delta && delta.enriched.length > 0 ? (
            <ul className="km-rail-recent">
              {delta.enriched.slice(0, 6).map((item) => (
                <li key={item.id}>
                  <button
                    type="button"
                    className="flex w-full items-center justify-between gap-2 text-left"
                    onClick={() => onSelectObject(item.id)}
                  >
                    <span className="min-w-0 truncate text-[12px] text-text">
                      {item.name}
                    </span>
                    <span className="shrink-0 text-[10px] text-faint">
                      {timeAgo(item.updated_at)}
                    </span>
                  </button>
                </li>
              ))}
            </ul>
          ) : (
            <p className="text-[12px] text-muted">
              Sin enriquecimientos en los últimos 7 días.
            </p>
          )}
        </div>
      </section>

      <section className="panel km-rail-panel">
        <header className="panel-header py-2.5">
          <h2 className="text-h3">Qué falta</h2>
          <Link
            to="/knowledge/health?tab=gaps"
            className="text-[11px] text-accent hover:underline"
          >
            Ver vacíos
          </Link>
        </header>
        <div className="panel-body">
          {gaps.length === 0 ? (
            <p className="text-[12px] text-muted">Sin vacíos abiertos.</p>
          ) : (
            <ul className="km-rail-gaps">
              {gaps.map((gap) => (
                <li key={gap.id}>
                  <span className="min-w-0 flex-1 truncate text-[12px] text-text">
                    {gap.title}
                  </span>
                  <span className="badge badge-muted shrink-0">{gap.priority}</span>
                </li>
              ))}
            </ul>
          )}
        </div>
      </section>
    </aside>
  );
}

export default MapRail;
