// =============================================================================
// WizardLearningPanel — "ZENT está aprendiendo" dentro del asistente
// =============================================================================
// El asistente guiado ya no muestra solo su anillo: sobre los mismos eventos
// reales del Knowledge Compiler muestra contadores vivos y descubrimientos.
// El enlace abre la experiencia completa sin perder el estado del wizard.
// =============================================================================
import { Broadcast, ArrowSquareOut } from "@phosphor-icons/react";
import { Link } from "react-router-dom";

import { timeAgo } from "../../lib/format";
import { PULSE_ROWS, AnimatedNumber } from "./KnowledgePulse";
import { stageLabel } from "./stages";
import { useLearningSession } from "./useLearningSession";

export function WizardLearningPanel({ sessionId }: { sessionId: string }) {
  const { detail, metrics, discoveries, stage, connected, active } =
    useLearningSession(sessionId, { includeGraph: false });

  if (!detail) return null;

  const inProgress = detail.sources.filter((source) =>
    ["pending", "learning"].includes(source.status)
  );
  const current = inProgress[0] ?? detail.sources.find((s) => s.status === "available");
  const lastDiscoveries = discoveries.slice(0, 3);

  return (
    <section className="ks-wizard-panel" data-testid="wizard-learning-panel">
      <header className="ks-wizard-head">
        <Broadcast size={14} weight="fill" className="text-accent" />
        <span className="text-[13px] text-text">
          {active || connected ? "ZENT está aprendiendo" : "ZENT aprendió esta información"}
        </span>
        <Link
          to={`/knowledge/sessions/${sessionId}`}
          target="_blank"
          rel="noreferrer"
          className="ks-wizard-link"
        >
          Ver aprendizaje en vivo
          <ArrowSquareOut size={12} weight="bold" />
        </Link>
      </header>

      <dl className="ks-wizard-metrics">
        {PULSE_ROWS.map((row) => (
          <div key={row.key}>
            <dt>{row.label}</dt>
            <dd>
              <AnimatedNumber value={metrics[row.key] ?? 0} />
            </dd>
          </div>
        ))}
      </dl>

      <p className="ks-wizard-meta">
        <span className="text-faint">Etapa:</span>{" "}
        <span className="text-muted">{stageLabel(stage)}</span>
        {current && (
          <>
            {" · "}
            <span className="text-faint">Procesando:</span>{" "}
            <span className="text-muted">{current.name}</span>
          </>
        )}
      </p>

      {lastDiscoveries.length > 0 && (
        <ul className="ks-wizard-feed">
          {lastDiscoveries.map((item) => (
            <li key={`${item.seq}-${item.event_type}`}>
              <span className="text-muted">{item.message}</span>
              <span className="text-faint">{timeAgo(item.at)}</span>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

export default WizardLearningPanel;
