// =============================================================================
// KnowledgeHero — qué sabe ZENT, en una pantalla
// =============================================================================
import {
  ArrowRight,
  MagnifyingGlass,
  Plus,
  Sparkle,
} from "@phosphor-icons/react";
import { Link } from "react-router-dom";
import { Button, ButtonLink, Skeleton, cn } from "../ui";
import type { KnowledgeDelta, KnowledgeOverview } from "../../lib/knowledgeModel";
import { interpretHealth } from "../../lib/knowledgeLanguage";
import { AnimatedNumber } from "./AnimatedNumber";
import { HealthIndicator } from "./badges";

type HeroMetric = { key: string; label: string; value: number; delta?: number };

function buildMetrics(
  overview: KnowledgeOverview,
  delta: KnowledgeDelta | null
): HeroMetric[] {
  const byType = overview.counts.by_type ?? {};
  const kind = (name: string) => byType[name]?.total ?? 0;
  const totals = delta?.totals;
  return [
    {
      key: "entities",
      label: "Entidades",
      value: kind("entity"),
      delta: totals?.entities,
    },
    {
      key: "relationships",
      label: "Relaciones",
      value: overview.counts.edges,
      delta: totals?.relationships,
    },
    {
      key: "facts",
      label: "Hechos",
      value: overview.counts.assertions,
      delta: totals?.facts,
    },
    {
      key: "rules",
      label: "Reglas",
      value: kind("business_rule"),
      delta: totals?.rules,
    },
    {
      key: "sources",
      label: "Fuentes",
      value: overview.counts.sources,
      delta: totals?.sources,
    },
  ];
}

export function KnowledgeHero({
  overview,
  delta,
  loading,
  onSearch,
}: {
  overview: KnowledgeOverview | null;
  delta: KnowledgeDelta | null;
  loading: boolean;
  onSearch: (query: string) => void;
}) {
  if (loading && !overview) {
    return (
      <section className="panel kh-hero" aria-busy="true">
        <div className="grid gap-6 p-5 lg:grid-cols-[1fr_280px] lg:p-6">
          <div className="flex flex-col gap-4">
            <Skeleton className="h-3 w-40 rounded-sm" />
            <Skeleton className="h-9 w-3/4 rounded-sm" />
            <Skeleton className="h-4 w-2/3 rounded-sm" />
            <div className="grid grid-cols-2 gap-3 sm:grid-cols-5">
              {[0, 1, 2, 3, 4].map((i) => (
                <Skeleton key={i} className="h-16 rounded-md" />
              ))}
            </div>
          </div>
          <Skeleton className="h-44 rounded-md" />
        </div>
      </section>
    );
  }

  if (!overview) return null;

  const empty = overview.state === "empty";
  const metrics = buildMetrics(overview, delta);
  const deltaItems = delta
    ? [
        { label: "entidades", value: delta.totals.entities },
        { label: "relaciones", value: delta.totals.relationships },
        { label: "hechos", value: delta.totals.facts },
        { label: "reglas", value: delta.totals.rules },
      ].filter((item) => item.value > 0)
    : [];

  return (
    <section className="panel kh-hero" data-testid="knowledge-hero">
      <div className="grid gap-6 p-5 lg:grid-cols-[1fr_300px] lg:p-6">
        <div className="flex min-w-0 flex-col">
          <p className="eyebrow flex items-center gap-2">
            <Sparkle size={12} weight="fill" className="text-accent" aria-hidden />
            ZENT KNOWLEDGE
          </p>
          <h1 className="mt-2 max-w-[24ch] text-[30px] font-semibold leading-[1.12] tracking-[-0.025em] text-text">
            {empty
              ? "ZENT todavía no tiene conocimiento de tu negocio."
              : "Tu conocimiento empresarial está creciendo"}
          </h1>
          <p className="prose-measure mt-2 text-sm leading-relaxed text-muted">
            {empty
              ? "Agrega tus primeras fuentes y observa cómo empieza a construir conocimiento."
              : overview.headline}
          </p>

          {!empty && (
            <>
              <dl className="mt-5 grid grid-cols-2 gap-3 sm:grid-cols-5">
                {metrics.map((metric) => (
                  <div key={metric.key} className="kh-hero-metric">
                    <dt>{metric.label}</dt>
                    <dd>
                      <AnimatedNumber value={metric.value} />
                    </dd>
                  </div>
                ))}
              </dl>
              <div className="mt-4 flex flex-wrap items-center gap-2">
                <span className="eyebrow">Últimas 24 h</span>
                {deltaItems.length > 0 ? (
                  deltaItems.map((item) => (
                    <span key={item.label} className="kh-delta-chip">
                      +{item.value.toLocaleString("es-PE")} {item.label}
                    </span>
                  ))
                ) : (
                  <span className="text-xs text-faint">
                    Sin cambios registrados en las últimas 24 h.
                  </span>
                )}
              </div>
            </>
          )}

          <form
            className="mt-5 flex max-w-xl gap-2"
            role="search"
            onSubmit={(event) => {
              event.preventDefault();
              const input = event.currentTarget.elements.namedItem(
                "knowledge-hero-search"
              ) as HTMLInputElement | null;
              const value = input?.value.trim() ?? "";
              if (value) onSearch(value);
            }}
          >
            <label className="sr-only" htmlFor="knowledge-hero-search">
              Buscar en el conocimiento
            </label>
            <div className="relative min-w-0 flex-1">
              <MagnifyingGlass
                size={15}
                className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-faint"
                aria-hidden
              />
              <input
                id="knowledge-hero-search"
                name="knowledge-hero-search"
                className="input pl-9"
                placeholder="Buscar un concepto, entidad, regla o fuente…"
                autoComplete="off"
              />
            </div>
            <Button type="submit" variant="secondary">
              Buscar
            </Button>
          </form>

          <div className="mt-4 flex flex-wrap items-center gap-2">
            <ButtonLink to="/knowledge/sources?new=1" variant="primary" leadingIcon={Plus}>
              Añadir fuente
            </ButtonLink>
            <ButtonLink
              to="/knowledge/explorer"
              variant="secondary"
              leadingIcon={ArrowRight}
            >
              Explorar conocimiento
            </ButtonLink>
          </div>
        </div>

        <aside className="kh-hero-health">
          <div className="flex items-center justify-between gap-3">
            <div>
              <p className="eyebrow">Knowledge Health</p>
              <p className="mt-1 text-xs text-muted">
                {overview.health.measured_dimensions} de {overview.health.total_dimensions}{" "}
                dimensiones medidas
              </p>
            </div>
            <HealthIndicator value={overview.health.overall} size={72} />
          </div>
          <p className="mt-3 text-[13px] leading-relaxed text-text">
            {interpretHealth(overview.health)}
          </p>
          <ul className="mt-3 flex flex-col gap-2">
            {overview.health.dimensions
              .filter((dimension) => dimension.measured && dimension.score != null)
              .slice(0, 4)
              .map((dimension) => (
                <li key={dimension.key} className="flex items-center gap-2">
                  <span className="min-w-0 flex-1 truncate text-xs text-muted">
                    {dimension.label}
                  </span>
                  <span className="mono text-xs tabular-nums text-text">
                    {Math.round(dimension.score!)}
                  </span>
                  <span className="h-1 w-14 overflow-hidden rounded-full bg-track" aria-hidden>
                    <span
                      className={cn(
                        "block h-full rounded-full",
                        dimension.score! >= 75
                          ? "bg-ok"
                          : dimension.score! >= 50
                            ? "bg-warn"
                            : "bg-danger"
                      )}
                      style={{ width: `${Math.max(4, dimension.score!)}%` }}
                    />
                  </span>
                </li>
              ))}
          </ul>
          <Link
            to="/knowledge/health"
            className="mt-4 inline-flex items-center gap-1.5 text-xs text-accent hover:underline"
          >
            Ver salud del conocimiento
            <ArrowRight size={12} aria-hidden />
          </Link>
        </aside>
      </div>

      {empty && overview.counts.indexed_documents > 0 && (
        <div className="border-t border-border px-5 py-3 text-xs text-muted lg:px-6">
          {overview.counts.indexed_documents.toLocaleString("es-PE")} documento(s) ya
          están listos para consulta en{" "}
          <Link to="/knowledge/sources" className="text-accent hover:underline">
            Fuentes
          </Link>
          . El modelo de negocio (entidades, reglas y métricas) se construye al
          aprender de bases de datos o catálogos.
        </div>
      )}
    </section>
  );
}
