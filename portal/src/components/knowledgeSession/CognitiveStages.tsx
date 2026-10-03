// =============================================================================
// CognitiveStages — las etapas cognitivas, expandibles y con datos reales
// =============================================================================
// Leyendo · Comprendiendo · Organizando · Conectando · Verificando · Aprendido
// Cada etapa muestra su detalle técnico (parser, semantic units, ...) y los
// contadores reales que produjo hasta ahora. Sin números inventados.
// =============================================================================
import { useEffect, useState } from "react";
import { CaretDown, CheckCircle, Circle, CircleNotch } from "@phosphor-icons/react";

import type { LearningSessionDetail } from "../../lib/knowledgeSessions";
import { deriveStageInsights } from "./learningInsights";

export function CognitiveStages({
  stages,
  metrics,
  current,
  finished,
}: {
  stages: LearningSessionDetail["stages"];
  metrics: Record<string, number>;
  current: string;
  finished: boolean;
}) {
  const insights = deriveStageInsights(stages, metrics, current, finished);
  const currentKey =
    insights.find((stage) => stage.state === "current")?.key ?? null;
  const [open, setOpen] = useState<string | null>(currentKey);
  const [touched, setTouched] = useState(false);

  // La etapa activa se expande sola mientras el usuario no haya interactuado.
  useEffect(() => {
    if (!touched && currentKey) setOpen(currentKey);
  }, [currentKey, touched]);

  return (
    <section className="panel ks-stages-panel" data-testid="learning-stages">
      <header className="panel-header">
        <div className="min-w-0">
          <p className="eyebrow">Etapas cognitivas</p>
          <h2 className="text-h3">Cómo ZENT convierte información en conocimiento</h2>
        </div>
      </header>
      <ol className="ks-cog-stages" aria-label="Etapas del aprendizaje">
        {insights.map((stage) => {
          const isOpen = open === stage.key;
          return (
            <li key={stage.key} className="ks-cog-stage" data-state={stage.state}>
              <button
                type="button"
                className="ks-cog-head"
                aria-expanded={isOpen}
                onClick={() => {
                  setTouched(true);
                  setOpen(isOpen ? null : stage.key);
                }}
              >
                <span className="ks-stage-icon" aria-hidden>
                  {stage.state === "done" && (
                    <CheckCircle size={16} weight="fill" className="text-ok" />
                  )}
                  {stage.state === "current" && (
                    <CircleNotch size={16} className="ks-spin text-accent" />
                  )}
                  {stage.state === "pending" && <Circle size={16} className="text-faint" />}
                </span>
                <span className="min-w-0 flex-1 text-left">
                  <span className="ks-cog-label">{stage.label}</span>
                  {stage.technical && (
                    <span className="ks-stage-tech">{stage.technical}</span>
                  )}
                </span>
                <CaretDown
                  size={12}
                  className={`ks-feed-caret ${isOpen ? "is-open" : ""}`}
                  aria-hidden
                />
              </button>
              {isOpen && (
                <div className="ks-cog-detail">
                  {stage.items.length === 0 ? (
                    <p className="text-[11px] text-faint">
                      {stage.state === "pending"
                        ? "Todavía no empezó."
                        : "Sin datos registrados para esta etapa."}
                    </p>
                  ) : (
                    <ul className="ks-cog-items">
                      {stage.items.map((item) => (
                        <li key={item.label}>
                          <span className="font-mono tabular-nums text-text">
                            {item.value}
                          </span>
                          <span className="text-faint">{item.label}</span>
                        </li>
                      ))}
                    </ul>
                  )}
                </div>
              )}
            </li>
          );
        })}
      </ol>
    </section>
  );
}

export default CognitiveStages;
