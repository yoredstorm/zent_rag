// =============================================================================
// Juicio previo (JEV) — los juicios que ocurrieron ANTES de generar (§34-§44)
// =============================================================================
// Un pack por momento: Preparación, Evidencia, Reconstrucción, Antes de generar,
// Verificación. Nunca se muestran las 15 tarjetas sueltas de un megaprompt: se
// muestra el pack ("8 preguntas · 1 llamada · 41 ms") y se expande la lista.
//
// Reglas:
// - Lenguaje humano primero; el detalle técnico (distribuciones, ids,
//   versiones) vive en el modo Técnico.
// - Cada juicio declara su EFECTO cuando cambió algo (§40).
// - Un juicio incierto no se disfraza de veredicto (§26, §44).
// =============================================================================

import { Badge } from "../../../components/ui";
import type { StoryJevImpact, StoryJudgment, StoryJudgmentPack } from "../executionStory";
import { reasonText } from "../executionStory";

const TYPE_TONES: Record<StoryJudgment["type"], "neutral" | "info" | "ok" | "warn"> = {
  choice: "info",
  score: "neutral",
  noul: "ok",
};

const UNCERTAIN_TONE = "warn" as const;

function readinessTone(state: string): "neutral" | "ok" | "warn" {
  if (state === "ok") return "ok";
  if (state === "blocked" || state === "warn") return "warn";
  return "neutral";
}

function JudgmentRow({ judgment }: { judgment: StoryJudgment }) {
  const uncertain = judgment.decisionKey === "uncertain" || judgment.ambiguous;
  return (
    <div className="flex flex-col gap-1 border-b border-border/50 py-2 last:border-0">
      <div className="flex flex-wrap items-center gap-2">
        <span className="text-sm text-text">{judgment.label}</span>
        <Badge tone={uncertain ? UNCERTAIN_TONE : TYPE_TONES[judgment.type]}>
          {judgment.typeLabel}
        </Badge>
        <span className="text-sm text-text tabular-nums">
          {uncertain ? "Incierto" : judgment.decisionLabel}
        </span>
        {judgment.confidence !== undefined ? (
          <span className="text-xs text-muted tabular-nums">
            {Math.round(judgment.confidence * 100)}%
          </span>
        ) : null}
        {judgment.certainty !== undefined ? (
          <span className="text-xs text-muted tabular-nums">
            certeza {Math.round(judgment.certainty * 100)}%
          </span>
        ) : null}
      </div>
      {judgment.ambiguous ? (
        <span className="text-xs text-warn">
          Dos alternativas quedaron muy cerca: no se trató como una elección clara.
        </span>
      ) : null}
      {judgment.effectLabel ? (
        <span className="text-xs text-muted">Efecto: {judgment.effectLabel}</span>
      ) : null}
      <JudgmentDistribution judgment={judgment} />
    </div>
  );
}

function JudgmentDistribution({ judgment }: { judgment: StoryJudgment }) {
  const probabilities =
    judgment.distribution && typeof judgment.distribution.probabilities === "object"
      ? (judgment.distribution.probabilities as Record<string, unknown>)
      : null;
  if (!probabilities) return null;
  const entries = Object.entries(probabilities)
    .map(([key, value]) => [key, Number(value)] as const)
    .filter(([, value]) => Number.isFinite(value))
    .sort((left, right) => right[1] - left[1])
    .slice(0, 5);
  if (entries.length < 2) return null;
  return (
    <div className="flex flex-wrap gap-2 text-[11px] text-faint tabular-nums">
      {entries.map(([key, value]) => (
        <span key={key}>
          {judgment.type === "choice" ? key.replace(/_/g, " ") : key}: {(value * 100).toFixed(0)}%
        </span>
      ))}
    </div>
  );
}

export function JudgmentPackCard({ pack }: { pack: StoryJudgmentPack }) {
  const headline = `${pack.judgmentCount} pregunta${pack.judgmentCount === 1 ? "" : "s"} · ${pack.cached ? "reutilizada" : "1 llamada"}${
    pack.durationMs ? ` · ${Math.round(pack.durationMs)} ms` : ""
  }`;
  return (
    <div className="flex flex-col gap-2">
      <div className="flex flex-wrap items-center gap-2">
        <span className="text-sm font-medium text-text">JEV · {pack.title}</span>
        <span className="text-xs text-muted tabular-nums">{headline}</span>
        {pack.tierLabel ? <Badge tone="info">{pack.tierLabel}</Badge> : null}
        {pack.allowGeneration === false ? <Badge tone="warn">Bloqueó la generación</Badge> : null}
        {pack.applied === false && pack.allowGeneration !== undefined ? (
          <Badge tone="neutral">Sólo observado</Badge>
        ) : null}
      </div>

      {pack.effectLabels.length ? (
        <div className="flex flex-col gap-1 text-xs text-muted">
          {pack.effectLabels.map((label) => (
            <span key={label}>Efecto: {label}</span>
          ))}
        </div>
      ) : (
        <span className="text-xs text-muted">
          Juicios informativos: ninguno cambió el camino de este run.
        </span>
      )}

      {pack.uncertain.length ? (
        <div className="flex flex-wrap items-center gap-2 rounded-md bg-warn-soft px-2 py-1 text-xs text-warn">
          <span>Juicio incierto</span>
          {pack.uncertain.slice(0, 4).map((id) => (
            <span key={id}>{id.replace(/_/g, " ")}</span>
          ))}
        </div>
      ) : null}

      {pack.reasonCodes.length ? (
        <div className="text-xs text-muted">
          Porque: {pack.reasonCodes.slice(0, 4).map(reasonText).join(", ")}
        </div>
      ) : null}

      {pack.readiness.length ? (
        <div className="flex flex-col gap-1">
          <span className="eyebrow">Preparación antes de generar</span>
          <div className="flex flex-wrap gap-2 text-xs">
            {pack.readiness.map((row) => (
              <span key={row.key} className="flex items-center gap-1 text-muted">
                <span className="text-text">{row.label}</span>
                <Badge tone={readinessTone(row.state)}>{row.stateLabel}</Badge>
                {row.confidence !== undefined ? (
                  <span className="tabular-nums">{Math.round(row.confidence * 100)}%</span>
                ) : null}
              </span>
            ))}
          </div>
        </div>
      ) : null}

      <details className="text-sm">
        <summary className="cursor-pointer text-xs text-muted">
          Ver las {pack.judgmentCount} preguntas
        </summary>
        <div className="mt-2 flex flex-col">
          {pack.judgments.map((judgment) => (
            <JudgmentRow key={judgment.id} judgment={judgment} />
          ))}
        </div>
        {pack.model ? (
          <span className="mt-2 block text-[11px] text-faint">
            modelo {pack.model}
            {pack.tokens ? ` · ${pack.tokens.input + pack.tokens.output} tokens` : ""}
            {pack.costUsd ? ` · $${pack.costUsd.toFixed(5)}` : ""}
          </span>
        ) : null}
      </details>
    </div>
  );
}

/** §43: la tarjeta de impacto del juicio previo. */
export function JevImpactCard({ impact }: { impact: StoryJevImpact }) {
  return (
    <div className="rounded-lg border border-border bg-surface/60 p-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <span className="eyebrow">Juicio previo (JEV)</span>
        <span className="text-xs text-muted">{impact.mode}</span>
      </div>
      <p className="mt-1 text-sm text-text">{impact.headline}</p>
      <dl className="mt-2 grid grid-cols-2 gap-x-4 gap-y-1 text-xs sm:grid-cols-3">
        {impact.facts.map((fact) => (
          <div key={fact.label} className="flex flex-col">
            <dt className="text-faint">{fact.label}</dt>
            <dd className="text-text tabular-nums">{fact.value}</dd>
          </div>
        ))}
      </dl>
      {impact.expensiveModelAvoided ? (
        <p className="mt-2 text-xs text-muted">
          Optimización: el juicio determinó que no hacía falta razonamiento generativo
          avanzado. Nivel de generación: {impact.tierLabel ?? "modelo pequeño"}.
        </p>
      ) : null}
    </div>
  );
}

/** §44: la incertidumbre explica por qué el run fue más largo. */
export function JudgmentUncertaintyNote({ impact }: { impact: StoryJevImpact }) {
  if (!impact.uncertainCritical) return null;
  return (
    <div className="rounded-lg border border-warn/40 bg-warn-soft p-3 text-sm text-warn">
      <span className="font-medium">Juicio incierto</span>
      <p className="mt-1 text-xs">
        {impact.uncertainCritical} juicio{impact.uncertainCritical === 1 ? "" : "s"} crítico
        {impact.uncertainCritical === 1 ? "" : "s"} quedó sin veredicto claro. Zent siguió con la
        ruta segura en lugar de asumir una conclusión.
      </p>
    </div>
  );
}
