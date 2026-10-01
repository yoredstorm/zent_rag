// =============================================================================
// KnowledgePulse — los contadores del aprendizaje real
// =============================================================================
// Cada número se anima SOLO cuando llega un evento real del Knowledge Compiler.
// No hay "actividad decorativa": si no pasa nada, el panel está quieto.
// =============================================================================
import { useEffect, useRef, useState } from "react";

import type { SessionSource } from "../../lib/knowledgeSessions";

export function AnimatedNumber({
  value,
  className = "",
}: {
  value: number;
  className?: string;
}) {
  const [display, setDisplay] = useState(value);
  const displayRef = useRef(value);

  useEffect(() => {
    const from = displayRef.current;
    if (from === value) return;
    const start = performance.now();
    const duration = 420;
    let raf = 0;
    const tick = (now: number) => {
      const t = Math.min(1, (now - start) / duration);
      const eased = 1 - Math.pow(1 - t, 3);
      const next = Math.round(from + (value - from) * eased);
      displayRef.current = next;
      setDisplay(next);
      if (t < 1) raf = requestAnimationFrame(tick);
    };
    raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf);
  }, [value]);

  return (
    <span className={`font-mono tabular-nums ${className}`}>
      {display.toLocaleString("es-PE")}
    </span>
  );
}

export const PULSE_ROWS: Array<{ key: string; label: string }> = [
  { key: "entities", label: "Entidades" },
  { key: "relationships", label: "Relaciones" },
  { key: "facts", label: "Hechos" },
  { key: "rules", label: "Reglas" },
  { key: "evidence", label: "Evidencias" },
];

export function KnowledgePulse({
  metrics,
  sources,
  stageLabel,
  active,
}: {
  metrics: Record<string, number>;
  sources: SessionSource[];
  stageLabel: string;
  active: boolean;
}) {
  const inProgress = sources.filter((source) =>
    ["pending", "learning"].includes(source.status)
  );
  const current = inProgress[0] ?? sources.find((source) => source.status === "available");

  return (
    <section
      className="panel ks-pulse"
      data-testid="knowledge-pulse"
      aria-label="Knowledge Pulse"
    >
      <header className="ks-pulse-head">
        <span className="ks-orb" aria-hidden>
          <span className="ks-orb-ring" />
          <span className="ks-orb-core" />
        </span>
        <div className="min-w-0">
          <p className="eyebrow">Knowledge Pulse</p>
          <h3 className="text-h3">
            {active ? "ZENT está aprendiendo" : "ZENT aprendió"}
          </h3>
        </div>
      </header>

      <dl className="ks-pulse-grid">
        {PULSE_ROWS.map((row) => (
          <div key={row.key} className="ks-pulse-metric">
            <dt>{row.label}</dt>
            <dd>
              <AnimatedNumber value={metrics[row.key] ?? 0} />
              {(metrics[row.key] ?? 0) > 0 && (
                <span className="ks-up" aria-hidden>
                  ↑
                </span>
              )}
            </dd>
          </div>
        ))}
      </dl>

      <footer className="ks-pulse-foot">
        <p className="text-[12px] text-muted">
          <span className="text-faint">Procesando:</span>{" "}
          <span className="text-text">
            {current ? current.name : active ? "preparando fuentes" : "sin actividad"}
          </span>
        </p>
        <p className="text-[11px] text-faint">
          Etapa: <span className="text-muted">{stageLabel}</span>
          {inProgress.length > 1 && (
            <>
              {" · "}
              {inProgress.length} fuentes en curso
            </>
          )}
        </p>
      </footer>
    </section>
  );
}

export default KnowledgePulse;
