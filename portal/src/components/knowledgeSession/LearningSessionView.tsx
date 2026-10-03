// =============================================================================
// LearningSessionView — "ZENT está aprendiendo tu empresa"
// =============================================================================
// Live Learning: estado, etapas cognitivas, Knowledge Pulse central, hitos,
// reencuentros con conocimiento existente, descubrimientos, fichas por fuente,
// resumen final con delta y modo técnico. Todo desde eventos reales.
// =============================================================================
import { useMemo, useState } from "react";
import { Link } from "react-router-dom";
import {
  ArrowLeft,
  Broadcast,
  CircleNotch,
  PlugsConnected,
  Wrench,
  WarningCircle,
} from "@phosphor-icons/react";

import { Button, ButtonLink } from "../ui";
import { CognitiveStages } from "./CognitiveStages";
import { DiscoveryFeed } from "./DiscoveryFeed";
import { KnowledgeMatches } from "./KnowledgeMatches";
import { LearningHero } from "./LearningHero";
import { LearningMilestones } from "./LearningMilestones";
import { LearningPulse } from "./LearningPulse";
import { LearningSummary } from "./LearningSummary";
import { LearningTechDrawer } from "./LearningTechDrawer";
import { SourceEvolution } from "./SourceEvolution";
import { deriveMatches, deriveMilestones } from "./learningInsights";
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
    events,
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
  const [techOpen, setTechOpen] = useState(false);

  const milestones = useMemo(
    () => deriveMilestones(events, detail),
    [events, detail]
  );
  const matches = useMemo(() => deriveMatches(events), [events]);

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
  const partial = detail.status === "partial" || detail.failed_sources > 0;

  return (
    <div className="ks-session" data-testid="learning-session">
      <header className="ks-head">
        <div className="min-w-0">
          <Link to="/knowledge/sources" className="ks-back">
            <ArrowLeft size={13} />
            Fuentes
          </Link>
          <h1 className="text-h1 ks-title">
            {detail.title || "Aprendizaje de conocimiento"}
          </h1>
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
              {detail.source_count} fuente{detail.source_count === 1 ? "" : "s"}
            </span>
          </div>
        </div>
        <Button
          variant="secondary"
          size="sm"
          leadingIcon={Wrench}
          onClick={() => setTechOpen(true)}
        >
          Ver detalles técnicos
        </Button>
      </header>

      {partial && (
        <div className="ks-recovery" role="status">
          <WarningCircle size={16} weight="fill" className="text-warn" />
          <p>
            {failed
              ? "ZENT no pudo completar esta sesión."
              : `ZENT aprendió ${detail.completed_sources} de ${detail.source_count} fuentes. ${detail.failed_sources} necesita${
                  detail.failed_sources === 1 ? "" : "n"
                } atención.`}{" "}
            <span className="text-muted">
              El resto del conocimiento está disponible: revisa el detalle en cada
              fuente para ver qué parte quedó parcialmente aprendida.
            </span>
          </p>
        </div>
      )}

      <LearningHero
        detail={detail}
        metrics={metrics}
        delta={delta}
        active={active}
        connected={connected}
      />

      <CognitiveStages
        stages={detail.stages}
        metrics={metrics}
        current={stage}
        finished={finished}
      />

      <div className="ks-live-grid">
        <LearningPulse
          graph={graph}
          events={events}
          active={active}
          metrics={metrics}
        />
        <div className="ks-live-side">
          <LearningMilestones milestones={milestones} />
          <KnowledgeMatches
            matches={matches.matches}
            matched={matches.matched}
            merged={matches.merged}
            reinforced={delta.reinforced_facts ?? 0}
            enriched={delta.enriched_entities ?? 0}
          />
        </div>
      </div>

      <div className="ks-live-grid is-two">
        <section className="panel" data-testid="what-zent-is-learning">
          <header className="panel-header">
            <div className="min-w-0">
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
            <div className="min-w-0">
              <p className="eyebrow">Fuentes</p>
              <h2 className="text-h3">Aprendizaje por archivo</h2>
            </div>
          </header>
          <div className="panel-body">
            <SourceEvolution sources={detail.sources} events={events} />
          </div>
        </section>
      </div>

      {(finished || failed) && (
        <LearningSummary detail={detail} delta={delta} />
      )}

      <LearningTechDrawer
        open={techOpen}
        onOpenChange={setTechOpen}
        detail={detail}
        events={events}
        metrics={metrics}
      />
    </div>
  );
}

export default LearningSessionView;
