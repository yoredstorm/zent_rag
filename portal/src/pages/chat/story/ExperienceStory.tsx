// =============================================================================
// ExperienceStory — la vista explicada de "Cómo llegó Zent a esta respuesta"
// =============================================================================
// Cinco secciones separadas: EJECUCIÓN, EVIDENCIA, DECISIONES, VERIFICACIÓN.
// Todo dato sale del contrato `flow.traceability` (una sola fuente de verdad).
// Nada se fabrica: un bloque sin telemetría no se renderiza.
// =============================================================================

import { useState } from "react";
import { Badge } from "../../../components/ui";
import { fmtCurrency } from "../../../lib/format";
import {
  effectLabel,
  reasonText,
  type ExecutionStory,
} from "../executionStory";
import {
  decisionAppliedCount,
  decisionResultText,
  displayConfidenceLabel,
  documentDisplayName,
  evidenceAuthorityLabel,
  evidenceLocation,
  evidenceMatchLabel,
  evidenceStatusText,
  evidenceUsageLabel,
  formatDisplayProbability,
  verificationCheckLabel,
  verificationCheckState,
  verificationExplanationLines,
  VERIFICATION_STATUS_TEXT,
  visibleExecutionSteps,
  type TraceDecision,
  type TraceDocument,
  type TraceEvidenceItem,
  type Traceability,
} from "../experience";

function toneFor(status: "ok" | "warn" | "neutral") {
  if (status === "ok") return "ok" as const;
  if (status === "warn") return "warn" as const;
  return "neutral" as const;
}

function fmtMs(value: number): string {
  if (value <= 0) return "—";
  if (value >= 1000) return `${(value / 1000).toFixed(1)} s`;
  return `${Math.round(value)} ms`;
}

// ---------------------------------------------------------------------------
// Cabecera: lo esencial antes de cualquier detalle
// ---------------------------------------------------------------------------

export function ExperienceHero({
  story,
  traceability,
}: {
  story: ExecutionStory;
  traceability: Traceability;
}) {
  const counts = traceability.counts;
  const interventions = decisionAppliedCount(traceability);
  const verification = VERIFICATION_STATUS_TEXT[traceability.verification.status];
  const used = counts.evidenceUsed;
  const metrics: Array<{ label: string; value: string }> = [
    {
      label: "Zent utilizó",
      value: [
        `${counts.documentsUsed} documento${counts.documentsUsed === 1 ? "" : "s"}`,
        `${used} evidencia${used === 1 ? "" : "s"}`,
      ].join(" · "),
    },
    {
      label: "JEV realizó",
      value: interventions
        ? `${interventions} ${interventions === 1 ? "intervención" : "intervenciones"}`
        : "Revisó sin cambiar el camino",
    },
    { label: "Verificación", value: verification.label },
    { label: "Tiempo", value: fmtMs(story.totalMs) },
    ...(story.costUsd === null
      ? []
      : [{ label: "Costo", value: fmtCurrency(story.costUsd, 6) }]),
  ];

  return (
    <header className="rounded-lg border border-border bg-surface p-4">
      <div className="flex flex-wrap items-center gap-2">
        <h2 className="text-h2 text-text">{headlineFor(traceability)}</h2>
        <Badge tone={toneFor(verification.tone)} dot>
          {verification.label}
        </Badge>
      </div>
      <dl className="mt-3 grid grid-cols-1 gap-x-4 gap-y-2 text-[12px] sm:grid-cols-2">
        {metrics.map((metric) => (
          <div key={metric.label}>
            <dt className="text-faint">{metric.label}</dt>
            <dd className="text-text">{metric.value}</dd>
          </div>
        ))}
      </dl>
    </header>
  );
}

function headlineFor(traceability: Traceability): string {
  switch (traceability.verification.status) {
    case "VERIFIED":
      return "Respuesta respaldada con conocimiento";
    case "PARTIALLY_VERIFIED":
      return "Respuesta respaldada parcialmente";
    case "CONFLICTING_EVIDENCE":
      return "Respuesta con evidencia en conflicto";
    case "INSUFFICIENT_EVIDENCE":
      return "Respuesta con evidencia insuficiente";
    default:
      return "Respuesta sin verificación completa";
  }
}

// ---------------------------------------------------------------------------
// 1. EJECUCIÓN
// ---------------------------------------------------------------------------

export function ExecutionSteps({ traceability }: { traceability: Traceability }) {
  const steps = visibleExecutionSteps(traceability);
  if (!steps.length) {
    return (
      <p className="text-[12.5px] text-muted">
        No hay pasos de ejecución registrados para esta respuesta.
      </p>
    );
  }
  return (
    <ol className="flex flex-col">
      {steps.map(({ event, presentation }, index) => (
        <li key={event.id} className="relative flex gap-3 pb-4 last:pb-0">
          <div className="flex shrink-0 flex-col items-center">
            <span className="flex h-6 w-6 items-center justify-center rounded-full border border-border bg-surface text-[11px] font-medium text-text">
              {index + 1}
            </span>
            {index < steps.length - 1 ? (
              <span className="mt-1 h-full w-px bg-border-soft" aria-hidden />
            ) : null}
          </div>
          <div className="min-w-0 flex-1 pt-0.5">
            <div className="flex flex-wrap items-center gap-2">
              <h3 className="text-[13px] font-medium text-text">{presentation.title}</h3>
              {event.durationMs !== undefined && event.durationMs > 0 ? (
                <span className="mono text-[11px] tabular-nums text-faint">
                  {fmtMs(event.durationMs)}
                </span>
              ) : null}
              {presentation.tone === "warn" ? <Badge tone="warn">requirió atención</Badge> : null}
            </div>
            {presentation.detail ? (
              <p className="mt-0.5 text-[12px] text-muted">{presentation.detail}</p>
            ) : null}
          </div>
        </li>
      ))}
    </ol>
  );
}

// ---------------------------------------------------------------------------
// 2. EVIDENCIA
// ---------------------------------------------------------------------------

export function EvidencePanel({ traceability }: { traceability: Traceability }) {
  const documents = traceability.documents;
  if (!documents.length) {
    return (
      <p className="text-[12.5px] text-muted">
        Esta respuesta no utilizó documentos recuperados.
      </p>
    );
  }
  const usedCount = traceability.counts.evidenceUsed;
  return (
    <div className="flex flex-col gap-3">
      <p className="text-[12px] text-faint">
        {documents.length} documento{documents.length === 1 ? "" : "s"} aportaron{" "}
        {usedCount} evidencia{usedCount === 1 ? "" : "s"} a la respuesta.
      </p>
      {documents.map((document) => (
        <DocumentBlock key={document.key} document={document} />
      ))}
    </div>
  );
}

function DocumentBlock({ document }: { document: TraceDocument }) {
  const [open, setOpen] = useState(document.usedCount > 0);
  return (
    <section className="rounded-md border border-border">
      <button
        type="button"
        className="flex w-full items-center justify-between gap-2 px-3 py-2 text-left"
        onClick={() => setOpen((value) => !value)}
        aria-expanded={open}
      >
        <span className="min-w-0">
          <span className="block truncate text-[12.5px] font-medium text-text">
            {documentDisplayName(document)}
          </span>
          <span className="text-[11px] text-faint">
            {document.usedCount} evidencia{document.usedCount === 1 ? "" : "s"} utilizada
            {document.usedCount === 1 ? "" : "s"}
            {document.evidenceCount > document.usedCount
              ? ` · ${document.evidenceCount} recuperada${document.evidenceCount === 1 ? "" : "s"}`
              : ""}
          </span>
        </span>
        <span className="shrink-0 text-[11.5px] text-accent">
          {open ? "Ocultar" : "Ver evidencias"}
        </span>
      </button>
      {open ? (
        <ul className="flex flex-col gap-2 border-t border-border-soft px-3 py-2">
          {document.items.map((item, index) => (
            <EvidenceBlock key={item.evidenceId ?? `${document.key}-${index}`} item={item} index={index} />
          ))}
        </ul>
      ) : null}
    </section>
  );
}

function EvidenceBlock({ item, index }: { item: TraceEvidenceItem; index: number }) {
  const [expanded, setExpanded] = useState(false);
  const location = evidenceLocation(item);
  const usage = evidenceUsageLabel(item);
  const match = evidenceMatchLabel(item);
  const authority = evidenceAuthorityLabel(item);
  const status = evidenceStatusText(item);
  const excerpt = item.excerpt ?? "";
  const long = excerpt.length > 180;
  return (
    <li className="rounded-sm border border-border-soft px-2.5 py-2">
      <div className="flex flex-wrap items-center gap-2 text-[11px]">
        <span className="font-medium text-text">Evidencia {index + 1}</span>
        {location ? <span className="text-faint">{location}</span> : null}
        {status ? <Badge tone={item.usedInAnswer ? "ok" : "neutral"}>{status}</Badge> : null}
        {authority ? <Badge tone="neutral">{authority}</Badge> : null}
      </div>
      {excerpt ? (
        <p className={`mt-1 whitespace-pre-wrap text-[12px] leading-5 text-muted ${expanded ? "" : "line-clamp-3"}`}>
          {excerpt}
        </p>
      ) : (
        <p className="mt-1 text-[11.5px] text-faint">
          El texto del fragmento no está disponible en la traza.
        </p>
      )}
      {long ? (
        <button
          type="button"
          className="mt-1 text-[11.5px] text-accent hover:underline"
          onClick={() => setExpanded((value) => !value)}
          aria-expanded={expanded}
        >
          {expanded ? "Ocultar fragmento" : "Ver contexto completo"}
        </button>
      ) : null}
      <div className="mt-1 flex flex-wrap gap-x-3 gap-y-1 text-[11px] text-faint">
        {usage ? <span className="text-muted">{usage}</span> : null}
        {match ? <span>Aporta: {match}</span> : null}
      </div>
    </li>
  );
}

// ---------------------------------------------------------------------------
// 3. DECISIONES
// ---------------------------------------------------------------------------

export function DecisionPanel({
  traceability,
  onOpenTechnical,
}: {
  traceability: Traceability;
  onOpenTechnical?: () => void;
}) {
  const relevant = traceability.decisions.filter(
    (decision) => decision.applied && decision.classification !== "OBSERVATIONAL",
  );
  const judgments = traceability.judgments.length;
  return (
    <div className="flex flex-col gap-2">
      {relevant.length ? (
        <p className="text-[12.5px] text-text">
          {relevant.length} decisi{relevant.length === 1 ? "ón" : "ones"} modific
          {relevant.length === 1 ? "ó" : "aron"} la ejecución.
        </p>
      ) : (
        <p className="text-[12.5px] text-muted">
          {judgments
            ? `JEV revisó la ejecución (${judgments} ${judgments === 1 ? "comprobación" : "comprobaciones"}). No fueron necesarios cambios.`
            : "JEV no participó en esta ejecución."}
        </p>
      )}
      {relevant.map((decision) => (
        <DecisionCard key={decision.id} decision={decision} />
      ))}
      {onOpenTechnical ? (
        <button
          type="button"
          className="self-start text-[11.5px] text-accent hover:underline"
          onClick={onOpenTechnical}
        >
          Ver diagnóstico JEV
        </button>
      ) : null}
    </div>
  );
}

function DecisionCard({ decision }: { decision: TraceDecision }) {
  const reasons = decision.reasonCodes.map(reasonText);
  const effects = decision.effectCodes.map(effectLabel);
  const confidence = displayConfidenceLabel(decision.display);
  const probability = formatDisplayProbability(decision.display);
  return (
    <article className="rounded-md border border-border bg-surface px-3 py-2.5">
      <div className="flex flex-wrap items-center gap-2">
        <Badge tone={decision.classification === "BLOCKING" ? "warn" : "accent"}>
          {decision.classification === "BLOCKING" ? "RETUVO LA RESPUESTA" : "AMPLIÓ LA EJECUCIÓN"}
        </Badge>
        <h3 className="text-[12.5px] font-medium uppercase tracking-wide text-text">
          {decision.actionLabel}
        </h3>
      </div>
      {reasons.length ? (
        <p className="mt-1.5 text-[12px] text-muted">
          <span className="text-faint">Motivo: </span>
          {reasons.join(", ")}
        </p>
      ) : null}
      {effects.length ? (
        <p className="mt-1 text-[12px] text-muted">
          <span className="text-faint">Acción: </span>
          {effects.join(", ")}
        </p>
      ) : null}
      {decisionResultText(decision) ? (
        <p className="mt-1 text-[12px] text-muted">
          <span className="text-faint">Resultado: </span>
          {decisionResultText(decision)}
        </p>
      ) : null}
      {confidence ? (
        <p className="mt-1 text-[11.5px] text-faint">
          Confianza: {confidence}
          {probability ? ` (${probability})` : ""}
        </p>
      ) : null}
    </article>
  );
}

// ---------------------------------------------------------------------------
// 4. VERIFICACIÓN
// ---------------------------------------------------------------------------

export function VerificationPanel({ traceability }: { traceability: Traceability }) {
  const verification = traceability.verification;
  const status = VERIFICATION_STATUS_TEXT[verification.status];
  const lines = verificationExplanationLines(verification);
  return (
    <div className="flex flex-col gap-2">
      <p className="text-[12.5px] text-text">{status.sentence}</p>
      {lines.length ? (
        <ul className="flex flex-col gap-1 text-[12px]">
          {lines.map((line) => (
            <li key={line.code} className="flex items-start gap-2">
              <span
                className={
                  line.tone === "ok"
                    ? "text-ok"
                    : line.tone === "warn"
                      ? "text-warn"
                      : "text-faint"
                }
                aria-hidden
              >
                {line.tone === "ok" ? "✓" : line.tone === "warn" ? "⚠" : "·"}
              </span>
              <span className="text-muted">{line.text}</span>
            </li>
          ))}
        </ul>
      ) : null}
      {verification.checks.length ? (
        <details className="rounded-sm border border-border-soft px-2.5 py-2">
          <summary className="cursor-pointer text-[11.5px] text-accent">
            Ver detalles técnicos
          </summary>
          <ul className="mt-1.5 flex flex-col gap-1 text-[11.5px]">
            {verification.checks.map((check) => (
              <li key={check.key} className="flex flex-wrap items-center gap-2 text-muted">
                <span className="text-text">{verificationCheckLabel(check.key)}</span>
                <Badge tone={check.state === "ok" ? "ok" : "neutral"}>
                  {verificationCheckState(check.state)}
                </Badge>
                {check.detail ? <span className="mono text-faint">{check.detail}</span> : null}
              </li>
            ))}
            {verification.signals.fallbackUsed && verification.signals.fallbackCode ? (
              <li className="flex flex-wrap items-center gap-2 text-muted">
                <span className="text-text">Validación alternativa</span>
                <span className="mono text-faint">
                  {verification.signals.fallbackCode}
                </span>
              </li>
            ) : null}
          </ul>
        </details>
      ) : null}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Composición
// ---------------------------------------------------------------------------

export function ExperienceStory({
  story,
  traceability,
  onOpenTechnical,
}: {
  story: ExecutionStory;
  traceability: Traceability;
  onOpenTechnical?: () => void;
}) {
  return (
    <div className="flex flex-col gap-5">
      <ExperienceHero story={story} traceability={traceability} />

      <section aria-labelledby="experience-execution">
        <p className="eyebrow mb-2" id="experience-execution">
          Cómo llegó Zent a esta respuesta
        </p>
        <ExecutionSteps traceability={traceability} />
      </section>

      <section aria-labelledby="experience-evidence">
        <p className="eyebrow mb-2" id="experience-evidence">
          Evidencia utilizada
        </p>
        <EvidencePanel traceability={traceability} />
      </section>

      <section aria-labelledby="experience-decisions">
        <p className="eyebrow mb-2" id="experience-decisions">
          Decisiones de JEV
        </p>
        <DecisionPanel traceability={traceability} onOpenTechnical={onOpenTechnical} />
      </section>

      <section aria-labelledby="experience-verification">
        <p className="eyebrow mb-2" id="experience-verification">
          Verificación de la respuesta
        </p>
        <VerificationPanel traceability={traceability} />
      </section>
    </div>
  );
}

export default ExperienceStory;
