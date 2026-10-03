// =============================================================================
// LearningHero — "ZENT está aprendiendo tu empresa"
// =============================================================================
// Estado, fuentes comprendidas, conocimiento descubierto y clasificación del
// cambio (nuevo/reforzado/actualizado/relacionado/conflictivo/ignorado).
// Todo viene de la sesión real: nada se simula.
// =============================================================================
import { Broadcast, CheckCircle, PlugsConnected, WarningCircle } from "@phosphor-icons/react";

import type { LearningSessionDetail } from "../../lib/knowledgeSessions";
import { AnimatedNumber } from "./KnowledgePulse";
import { taxonomyCounts, TAXONOMY_KEYS, type TaxonomyKey } from "./learningInsights";

const TAXONOMY_COPY: Record<TaxonomyKey, { label: string; hint: string; tone: string }> = {
  new: {
    label: "Nuevo",
    hint: "conocimiento que ZENT no tenía",
    tone: "text-accent",
  },
  reinforced: {
    label: "Reforzado",
    hint: "conocimiento existente con nuevo respaldo",
    tone: "text-info",
  },
  updated: {
    label: "Actualizado",
    hint: "nueva versión o vigencia",
    tone: "text-warn",
  },
  related: {
    label: "Conectado",
    hint: "relaciones nuevas entre conocimiento existente",
    tone: "text-info",
  },
  conflicting: {
    label: "Conflicto",
    hint: "información posiblemente incompatible",
    tone: "text-warn",
  },
  ignored: {
    label: "Ignorado",
    hint: "duplicado o contenido sin valor semántico",
    tone: "text-faint",
  },
};

const HERO_METRICS: Array<{ key: string; label: string }> = [
  { key: "entities", label: "conceptos" },
  { key: "facts", label: "hechos" },
  { key: "relationships", label: "relaciones" },
  { key: "rules", label: "reglas" },
  { key: "evidence", label: "evidencias" },
];

export function LearningHero({
  detail,
  metrics,
  delta,
  active,
  connected,
}: {
  detail: LearningSessionDetail;
  metrics: Record<string, number>;
  delta: Record<string, number>;
  active: boolean;
  connected: boolean;
}) {
  const finished = ["completed", "partial"].includes(detail.status);
  const total = Math.max(1, detail.source_count);
  const completed = detail.completed_sources;
  const progress = Math.min(100, Math.round((completed / total) * 100));
  const taxonomy = taxonomyCounts(delta);
  const partial = detail.status === "partial" || detail.failed_sources > 0;

  return (
    <section className="panel ks-hero" data-testid="learning-hero">
      <div className="ks-hero-main">
        <p className="eyebrow flex items-center gap-2">
          <Broadcast size={12} weight="fill" className="text-accent" aria-hidden />
          LIVE LEARNING
        </p>
        <h1 className="ks-hero-title">
          {active
            ? "ZENT está aprendiendo"
            : finished
              ? "ZENT aprendió esta información"
              : "Sesión de aprendizaje"}
        </h1>
        <p className="ks-hero-sub">
          {active
            ? "Comprendiendo y conectando conocimiento"
            : partial
              ? "El conocimiento quedó disponible; hay puntos por revisar"
              : "El conocimiento de tu empresa creció con esta carga"}
        </p>

        <div className="ks-hero-progress" data-testid="learning-progress">
          <div className="flex items-baseline justify-between gap-3">
            <span className="text-[13px] text-text">
              Fuentes comprendidas{" "}
              <span className="font-mono tabular-nums">
                {completed} / {detail.source_count}
              </span>
            </span>
            <span className="text-[11px] text-faint">
              {progress}% ·{" "}
              {detail.available_sources} consultable
              {detail.available_sources === 1 ? "" : "s"}
            </span>
          </div>
          <span className="ks-hero-bar" aria-hidden>
            <span style={{ width: `${progress}%` }} />
          </span>
        </div>

        <dl className="ks-hero-metrics">
          {HERO_METRICS.map((metric) => (
            <div key={metric.key}>
              <dt>{metric.label}</dt>
              <dd>
                <AnimatedNumber value={metrics[metric.key] ?? 0} />
              </dd>
            </div>
          ))}
        </dl>
      </div>

      <aside className="ks-hero-side">
        <div className="flex items-center gap-2 text-[12px]">
          {active ? (
            <span className="ks-live" data-connected={connected}>
              <Broadcast size={13} weight="fill" className="text-accent" aria-hidden />
              {connected ? "En vivo" : "Sincronizando…"}
            </span>
          ) : (
            <span className="ks-live">
              <PlugsConnected size={13} weight="bold" className="text-muted" aria-hidden />
              Sesión cerrada
            </span>
          )}
          {partial && (
            <span className="flex items-center gap-1 text-warn">
              <WarningCircle size={13} weight="fill" aria-hidden />
              {detail.failed_sources} por revisar
            </span>
          )}
          {!active && !partial && (
            <span className="flex items-center gap-1 text-ok">
              <CheckCircle size={13} weight="fill" aria-hidden />
              Completado
            </span>
          )}
        </div>

        {detail.is_available && (
          <p className="ks-hero-available" data-testid="partial-availability">
            <CheckCircle size={13} weight="fill" className="text-ok" aria-hidden />
            {active
              ? "Ya puedes consultar esta información. ZENT continúa conectando y verificando en segundo plano."
              : "Esta información ya está disponible para tus agentes y búsquedas."}
          </p>
        )}

        <div className="ks-taxonomy-live" data-testid="learning-taxonomy-live">
          {TAXONOMY_KEYS.map((key) => (
            <div key={key} className="ks-taxonomy-live-item" title={TAXONOMY_COPY[key].hint}>
              <span className="ks-taxonomy-live-label">{TAXONOMY_COPY[key].label}</span>
              <span className={`ks-taxonomy-live-value ${TAXONOMY_COPY[key].tone}`}>
                <AnimatedNumber value={taxonomy[key]} />
              </span>
            </div>
          ))}
        </div>
      </aside>
    </section>
  );
}

export default LearningHero;
