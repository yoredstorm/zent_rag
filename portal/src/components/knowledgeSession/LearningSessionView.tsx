// =============================================================================
// LearningSessionView — "ZENT está aprendiendo tu negocio"
// =============================================================================
// Composición de la experiencia de aprendizaje:
//   - estado y etapas humanas (Leyendo → Aprendido)
//   - Knowledge Pulse con contadores reales
//   - "Qué está aprendiendo" (descubrimientos agrupados)
//   - evolución por fuente (documentos y Excel)
//   - grafo vivo de la sesión
//   - resumen final con delta y antes/después
//
// Desktop: panel principal + columna viva. Mobile: estado, descubrimientos,
// métricas, fuentes; el grafo queda como vista secundaria.
// =============================================================================
import { Link } from "react-router-dom";
import {
  ArrowLeft,
  Broadcast,
  CircleNotch,
  PlugsConnected,
  WarningCircle,
} from "@phosphor-icons/react";

import { ButtonLink } from "../ui/Button";
import { DiscoveryFeed } from "./DiscoveryFeed";
import { KnowledgeGraphLive } from "./KnowledgeGraphLive";
import { KnowledgePulse } from "./KnowledgePulse";
import { LearningStages } from "./LearningStages";
import { LearningSummary } from "./LearningSummary";
import { SourceEvolution } from "./SourceEvolution";
import { stageLabel } from "./stages";
import { useLearningSession } from "./useLearningSession";

const STATUS_COPY: Record<string, { label: string; tone: string }> = {
  preparing: { label: "Preparando", tone: "badge-pending" },
  learning: { label: "Aprendiendo", tone: "badge-accent" },
  available: { label: "Disponible para consultar", tone: "badge-info" },
  optimizing: { label: "Optimizando conocimiento", tone: "badge-info" },
  completed: { label: "Aprendizaje completado", tone: "badge-ok" },
  partial: { label: "Aprendizaje parcial", tone: "badge-pending" },
  failed: { label: "No se pudo completar", tone: "badge-danger" },
  canceled: { label: "Cancelado", tone: "badge-muted" },
};

export function LearningSessionView({ sessionId }: { sessionId: string }) {
  const {
    detail,
    graph,
    metrics,
    delta,
    discoveries,
    stage,
    connected,
    loading,
    error,
    active,
  } = useLearningSession(sessionId);

  if (loading && !detail) {
    return (
      <div className="ks-loading" data-testid="learning-session-loading">
        <CircleNotch size={20} className="ks-spin text-accent" />
        <p className="text-[13px] text-muted">Cargando la sesión de aprendizaje…</p>
      </div>
    );
  }

  if (!detail) {
    return (
      <div className="panel ks-empty" data-testid="learning-session-error">
        <WarningCircle size={22} weight="fill" className="text-danger" />
        <h2 className="text-h3">No se pudo abrir la sesión</h2>
        <p className="text-[13px] text-muted">
          {error || "La sesión no existe o no pertenece a tu organización."}
        </p>
        <ButtonLink to="/knowledge/sources" variant="secondary" size="sm">
          Volver a Fuentes
        </ButtonLink>
      </div>
    );
  }

  const status = STATUS_COPY[detail.status] ?? {
    label: detail.status,
    tone: "badge-muted",
  };
  const finished = ["completed", "partial"].includes(detail.status);
  const failed = detail.status === "failed";

  return (
    <div className="ks-session" data-testid="learning-session">
      <header className="ks-head">
        <div className="min-w-0">
          <Link to="/knowledge/sources" className="ks-back">
            <ArrowLeft size={13} />
            Fuentes
          </Link>
          <h1 className="text-h1 ks-title">{detail.title || "Aprendizaje de conocimiento"}</h1>
          <div className="ks-head-meta">
            <span className={`badge ${status.tone}`}>{status.label}</span>
            <span className="ks-live" data-connected={connected}>
              {active ? (
                <>
                  <Broadcast size={13} weight="fill" className="text-accent" />
                  {connected ? "En vivo" : "Sincronizando…"}
                </>
              ) : (
                <>
                  <PlugsConnected size={13} weight="bold" className="text-muted" />
                  Sesión cerrada
                </>
              )}
            </span>
            <span className="text-faint text-[12px]">
              {detail.source_count} fuente{detail.source_count === 1 ? "" : "s"} ·{" "}
              {detail.available_sources} disponible
              {detail.available_sources === 1 ? "" : "s"} para consultar
            </span>
          </div>
        </div>
      </header>

      {(detail.failed_sources > 0 || failed) && (
        <div className="ks-recovery" role="status">
          <WarningCircle size={16} weight="fill" className="text-warn" />
          <p>
            {failed
              ? "ZENT no pudo completar esta sesión."
              : `ZENT tuvo un problema con ${detail.failed_sources} fuente${
                  detail.failed_sources === 1 ? "" : "s"
                }. Las demás continuaron procesándose y quedaron aprendidas.`}{" "}
            <span className="text-muted">
              Revisa el detalle en cada fuente para ver qué parte quedó parcialmente
              aprendida.
            </span>
          </p>
        </div>
      )}

      <div className="ks-layout">
        <div className="ks-block-pulse">
          <KnowledgePulse
            metrics={metrics}
            sources={detail.sources}
            stageLabel={stageLabel(stage)}
            active={active}
          />
        </div>

        <div className="ks-main">
          <section className="panel ks-stages-panel">
            <LearningStages stages={detail.stages} current={stage} />
          </section>

          <section className="panel" data-testid="what-zent-is-learning">
            <header className="panel-header">
              <div>
                <p className="eyebrow">Qué está aprendiendo</p>
                <h2 className="text-h3">Descubrimientos</h2>
              </div>
            </header>
            <div className="panel-body">
              <DiscoveryFeed discoveries={discoveries} sources={detail.sources} />
            </div>
          </section>

          <section className="panel" data-testid="session-sources">
            <header className="panel-header">
              <div>
                <p className="eyebrow">Fuentes</p>
                <h2 className="text-h3">
                  Evolución del aprendizaje por fuente
                </h2>
              </div>
            </header>
            <div className="panel-body">
              <SourceEvolution sources={detail.sources} />
            </div>
          </section>

          {(finished || failed) && (
            <LearningSummary detail={detail} delta={delta} />
          )}
        </div>

        <div className="ks-block-graph">
          <section className="panel" data-testid="session-graph-panel">
            <header className="panel-header">
              <div>
                <p className="eyebrow">Knowledge Graph</p>
                <h2 className="text-h3">Conexiones de esta sesión</h2>
              </div>
            </header>
            <div className="panel-body">
              <KnowledgeGraphLive graph={graph} active={active} />
            </div>
          </section>
        </div>
      </div>
    </div>
  );
}

export default LearningSessionView;
