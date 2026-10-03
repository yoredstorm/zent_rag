// =============================================================================
// LearningMilestones — solo los momentos que importan
// =============================================================================
// Derivados de eventos reales de alto valor (conexiones entre áreas conocidas,
// versiones nuevas, conflictos, fusiones, descubrimientos grandes). Nunca un
// toast por evento: solo hitos.
// =============================================================================
import {
  ArrowsClockwise,
  CheckCircle,
  GitMerge,
  LinkSimple,
  ShieldWarning,
  Sparkle,
  Stack,
  WarningCircle,
} from "@phosphor-icons/react";

import { timeAgo } from "../../lib/format";
import type { Milestone, MilestoneKind } from "./learningInsights";

const KIND_META: Record<
  MilestoneKind,
  { icon: React.ReactNode; tone: string; label: string }
> = {
  connection: {
    icon: <LinkSimple size={14} weight="bold" className="text-info" />,
    tone: "is-info",
    label: "Conexión",
  },
  version: {
    icon: <ArrowsClockwise size={14} weight="bold" className="text-warn" />,
    tone: "is-warn",
    label: "Versión",
  },
  conflict: {
    icon: <ShieldWarning size={14} weight="fill" className="text-warn" />,
    tone: "is-warn",
    label: "Revisión",
  },
  merge: {
    icon: <GitMerge size={14} weight="bold" className="text-info" />,
    tone: "is-info",
    label: "Consolidación",
  },
  discovery: {
    icon: <Sparkle size={14} weight="fill" className="text-accent" />,
    tone: "is-accent",
    label: "Descubrimiento",
  },
  rule: {
    icon: <Stack size={14} weight="fill" className="text-accent" />,
    tone: "is-accent",
    label: "Reglas",
  },
  available: {
    icon: <CheckCircle size={14} weight="fill" className="text-ok" />,
    tone: "is-ok",
    label: "Disponible",
  },
  completed: {
    icon: <CheckCircle size={14} weight="fill" className="text-ok" />,
    tone: "is-ok",
    label: "Aprendido",
  },
};

export function LearningMilestones({
  milestones,
}: {
  milestones: Milestone[];
}) {
  if (milestones.length === 0) {
    return (
      <section className="panel ks-milestones" data-testid="learning-milestones">
        <header className="panel-header">
          <div className="min-w-0">
            <p className="eyebrow">Momentos importantes</p>
            <h2 className="text-h3">Lo que destacó</h2>
          </div>
        </header>
        <div className="panel-body">
          <p className="flex items-center gap-2 text-[13px] text-faint">
            <WarningCircle size={14} aria-hidden />
            Todavía no hay hitos. Aparecerán cuando ZENT conecte, consolide o
            detecte algo relevante.
          </p>
        </div>
      </section>
    );
  }

  return (
    <section className="panel ks-milestones" data-testid="learning-milestones">
      <header className="panel-header">
        <div className="min-w-0">
          <p className="eyebrow">Momentos importantes</p>
          <h2 className="text-h3">Lo que destacó</h2>
        </div>
      </header>
      <ul className="ks-milestone-list">
        {milestones.map((milestone) => {
          const meta = KIND_META[milestone.kind];
          return (
            <li
              key={milestone.id}
              className={`ks-milestone ${meta.tone}`}
              data-kind={milestone.kind}
            >
              <span className="ks-milestone-icon" aria-hidden>
                {meta.icon}
              </span>
              <span className="min-w-0 flex-1">
                <span className="ks-milestone-kind">{meta.label}</span>
                <span className="ks-milestone-title">{milestone.title}</span>
                {milestone.detail && (
                  <span className="ks-milestone-detail">{milestone.detail}</span>
                )}
              </span>
              {milestone.at && (
                <time className="ks-milestone-time" dateTime={milestone.at}>
                  {timeAgo(milestone.at)}
                </time>
              )}
            </li>
          );
        })}
      </ul>
    </section>
  );
}

export default LearningMilestones;
