// =============================================================================
// KnowledgeHero — qué sabe ZENT, en una pantalla
// =============================================================================
// Una idea factual, un CTA principal y tres señales con alcance explícito.
// La salud se explica; no se reduce a un número sin contexto.
// =============================================================================
import {
  ArrowRight,
  ChatCircleDots,
  Plus,
  Sparkle,
  WarningCircle,
} from "@phosphor-icons/react";
import { Link } from "react-router-dom";
import { ButtonLink, Skeleton } from "../ui";
import type { KnowledgeDelta, KnowledgeOverview } from "../../lib/knowledgeModel";
import { interpretHealth } from "../../lib/knowledgeLanguage";
import { AnimatedNumber } from "./AnimatedNumber";

type HeroMetric = {
  key: string;
  label: string;
  value: number;
  hint: string;
};

function buildMetrics(overview: KnowledgeOverview): HeroMetric[] {
  const counts = overview.counts;
  const readySources =
    typeof counts.sources_ready === "number"
      ? counts.sources_ready
      : counts.indexed_sources;
  const attention = overview.attention.reduce(
    (total, item) => total + (Number(item.count) || 0),
    0,
  );
  return [
    {
      key: "documents",
      label: "Documentos listos",
      value: counts.indexed_documents,
      hint: "Documentos con contenido activo, listos para citar.",
    },
    {
      key: "sources",
      label: "Fuentes con contenido",
      value: readySources,
      hint: "Fuentes de tu biblioteca que tienen documentos disponibles.",
    },
    {
      key: "attention",
      label: "Señales de atención",
      value: attention,
      hint: "Incidencias distintas que necesitan una decisión humana.",
    },
  ];
}

export function KnowledgeHero({
  overview,
  delta,
  loading,
}: {
  overview: KnowledgeOverview | null;
  delta: KnowledgeDelta | null;
  loading: boolean;
}) {
  if (loading && !overview) {
    return (
      <section className="panel kh-hero" aria-busy="true">
        <div className="grid gap-6 p-5 lg:grid-cols-[1fr_280px] lg:p-6">
          <div className="flex flex-col gap-4">
            <Skeleton className="h-3 w-40 rounded-sm" />
            <Skeleton className="h-9 w-3/4 rounded-sm" />
            <Skeleton className="h-4 w-2/3 rounded-sm" />
            <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
              {[0, 1, 2].map((i) => (
                <Skeleton key={i} className="h-20 rounded-md" />
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
  const metrics = buildMetrics(overview);
  const deltaItems = delta
    ? [
        { label: "entidades", value: delta.totals.entities },
        { label: "relaciones", value: delta.totals.relationships },
        { label: "hechos", value: delta.totals.facts },
        { label: "reglas", value: delta.totals.rules },
      ].filter((item) => item.value > 0)
    : [];
  const measured = overview.health.measured_dimensions;
  const total = overview.health.total_dimensions;

  return (
    <section className="panel kh-hero" data-testid="knowledge-hero">
      <div className="grid gap-6 p-5 lg:grid-cols-[1fr_300px] lg:p-6">
        <div className="flex min-w-0 flex-col">
          <p className="eyebrow flex items-center gap-2">
            <Sparkle size={12} weight="fill" className="text-accent" aria-hidden />
            ZENT KNOWLEDGE
          </p>
          <h1 className="mt-2 max-w-[26ch] text-[30px] font-semibold leading-[1.12] tracking-[-0.025em] text-text">
            {empty
              ? "Todavía no hay información lista para responder."
              : overview.headline || "ZENT tiene información lista para consultar."}
          </h1>
          <p className="prose-measure mt-2 text-sm leading-relaxed text-muted">
            {empty
              ? "Añade un documento o conecta un sistema. Verás qué se recibe, qué se está procesando y cuándo puedes preguntar."
              : "Los números describen documentos y fuentes disponibles; no son una estimación de lo que ZENT entiende."}
          </p>

          {!empty && (
            <>
              <dl className="mt-5 grid grid-cols-1 gap-3 sm:grid-cols-3">
                {metrics.map((metric) => (
                  <div key={metric.key} className="kh-hero-metric" title={metric.hint}>
                    <dt>{metric.label}</dt>
                    <dd>
                      <AnimatedNumber value={metric.value} />
                    </dd>
                    <span className="mt-1 block text-[10px] leading-snug text-faint">
                      {metric.hint}
                    </span>
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
                    Sin cambios medidos en las últimas 24 h.
                  </span>
                )}
              </div>
            </>
          )}

          <div className="mt-5 flex flex-wrap items-center gap-2">
            {empty ? (
              <ButtonLink to="/knowledge/sources?new=1" variant="primary" leadingIcon={Plus}>
                Añadir información
              </ButtonLink>
            ) : (
              <ButtonLink to="/knowledge/ask" variant="primary" leadingIcon={ChatCircleDots}>
                Preguntar
              </ButtonLink>
            )}
            <ButtonLink
              to="/knowledge/sources"
              variant="ghost"
              leadingIcon={ArrowRight}
            >
              Ver fuentes
            </ButtonLink>
          </div>
        </div>

        <aside className="kh-hero-health" aria-label="Qué está medido">
          <div className="flex items-center justify-between gap-3">
            <div>
              <p className="eyebrow">Qué está medido</p>
              <p className="mt-1 text-xs text-muted">
                {measured} de {total} señales con datos
              </p>
            </div>
            <WarningCircle
              size={22}
              className={measured === 0 ? "text-faint" : "text-warn"}
              aria-hidden
            />
          </div>
          <p className="mt-3 text-[13px] leading-relaxed text-text">
            {interpretHealth(overview.health)}
          </p>
          <ul className="mt-3 flex flex-col gap-2">
            {overview.health.dimensions.slice(0, 4).map((dimension) => (
              <li key={dimension.key} className="flex items-center gap-2">
                <span className="min-w-0 flex-1 truncate text-xs text-muted">
                  {dimension.label}
                </span>
                <span className="text-[11px] text-faint">
                  {dimension.measured && dimension.score != null
                    ? "medido"
                    : "no medido"}
                </span>
              </li>
            ))}
          </ul>
          <Link
            to="/knowledge/improve"
            className="mt-4 inline-flex items-center gap-1.5 text-xs text-accent hover:underline"
          >
            Ver qué mejorar
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
