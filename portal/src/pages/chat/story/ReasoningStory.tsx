// =============================================================================
// ReasoningStory — escenario, cadena de estados, hipótesis, inferencia y
// completitud del análisis (§13-§22)
// =============================================================================
// La timeline se construye desde el StateTransitionSet del backend, nunca desde
// texto generado por un LLM.
import { useState } from "react";
import { Badge, type Tone } from "../../../components/ui";
import { eventReasonsText, verdictLabel, type StoryEvent, type StoryHypothesis } from "../executionStory";

function verdictTone(verdict: string): Tone {
  // §20: una hipótesis descartada no es un error.
  if (verdict === "SUPPORTED") return "ok";
  if (verdict === "REJECTED") return "neutral";
  return "warn";
}

function verdictGlyph(verdict: string): string {
  if (verdict === "SUPPORTED") return "✓";
  if (verdict === "REJECTED") return "✕";
  return "?";
}

export function ReasoningStory({ event }: { event: StoryEvent }) {
  if (event.kind === "scenario_parse") return <ScenarioCard event={event} />;
  if (event.kind === "state_reconstruction") return <TransitionCard event={event} />;
  if (event.kind === "hypothesis_test") return <HypothesisList event={event} />;
  if (event.kind === "analysis_completion") return <CompletionCard event={event} />;
  if (event.kind === "inference_verification") return <InferenceCard event={event} />;
  if (event.kind === "reasoning_plan") return <PlanCard event={event} />;
  if (event.kind === "company_context") return <CompanyContextCard event={event} />;
  return null;
}

function PlanCard({ event }: { event: StoryEvent }) {
  const plan = (event.plan ?? {}) as Record<string, unknown>;
  const operations = Array.isArray(plan.operations) ? (plan.operations as unknown[]) : [];
  const requires = (plan.requires ?? {}) as Record<string, unknown>;
  const question = String(plan.question_to_prove ?? "");
  const needs = Object.entries(requires)
    .filter(([, value]) => value === true)
    .map(([key]) => key.replace(/_/g, " "));
  const skips = Object.entries(requires)
    .filter(([, value]) => value === false)
    .map(([key]) => key.replace(/_/g, " "));
  return (
    <div className="mt-1.5 flex flex-col gap-1.5 text-[11.5px] text-muted">
      {question ? (
        <p>
          <span className="text-faint">Pregunta que intentó demostrar: </span>
          <span className="text-text">{question}</span>
        </p>
      ) : null}
      {operations.length ? <p>{operations.length} pasos requeridos</p> : null}
      {needs.length ? <p>Necesita: {needs.join(", ")}</p> : null}
      {skips.length ? <p>No necesita: {skips.join(", ")}</p> : null}
    </div>
  );
}

function CompanyContextCard({ event }: { event: StoryEvent }) {
  const counts = (event.metrics.company_context ?? {}) as Record<string, number>;
  const labels: Array<[string, string]> = [
    ["concepts", "conceptos"],
    ["rules", "reglas"],
    ["systems", "sistemas"],
    ["processes", "procesos"],
    ["mappings", "relaciones técnicas"],
    ["memories", "memoria operativa"],
  ];
  const entries = labels.filter(([key]) => Number(counts[key]) > 0);
  if (!entries.length) return null;
  return (
    <div className="mt-1 flex flex-wrap gap-x-4 gap-y-1 text-[11.5px] text-muted">
      {entries.map(([key, label]) => (
        <span key={key}>
          {counts[key]} {label}
        </span>
      ))}
      {event.technical?.truncated ? <Badge tone="warn">contexto truncado</Badge> : null}
    </div>
  );
}

function ScenarioCard({ event }: { event: StoryEvent }) {
  const scenario = (event.scenario ?? {}) as Record<string, unknown>;
  const events = Number(scenario.events ?? 0);
  const unparsed = Number(scenario.unparsed ?? 0);
  const recordTypes = Number(scenario.record_types ?? 0);
  const schemas = Number(scenario.schemas ?? 0);
  const missing = Array.isArray(scenario.missing_requirements)
    ? (scenario.missing_requirements as Array<Record<string, unknown>>)
    : [];
  return (
    <div className="mt-1.5 flex flex-col gap-1 text-[11.5px] text-muted">
      <span className="text-text">
        {events} registros identificados · {recordTypes} tipos de registro
      </span>
      <span>
        {schemas ? "✓" : "⚠"} {schemas ? "schema encontrado" : "sin schema conocido"}
      </span>
      {unparsed ? (
        <span className="text-warn">
          ⚠ {unparsed} registros no pudieron interpretarse
        </span>
      ) : (
        <span className="text-ok">✓ 0 elementos sin interpretar</span>
      )}
      {missing.length ? (
        <span className="text-warn">
          Motivo:{" "}
          {missing
            .map((item) => eventReasonsText({ ...event, completion: undefined, decisionReasonCodes: [String(item.kind)] }))
            .join(", ")}
        </span>
      ) : null}
    </div>
  );
}

function TransitionCard({ event }: { event: StoryEvent }) {
  const [expanded, setExpanded] = useState(false);
  const transitions = event.transitions;
  if (!transitions.length) return null;
  const confirmed = transitions.filter((link) => link.status === "CONFIRMED").length;
  const unresolved = transitions.length - confirmed;
  const visible = expanded ? transitions : transitions.slice(0, 12);
  return (
    <div className="mt-1.5 flex flex-col gap-1.5">
      <div className="flex flex-wrap gap-x-4 gap-y-1 text-[11.5px] text-muted">
        <span>{confirmed} transiciones confirmadas</span>
        {unresolved ? (
          <span className="text-warn">⚠ {unresolved} sin demostrar</span>
        ) : (
          <span className="text-ok">0 transiciones desconocidas</span>
        )}
      </div>
      <div className="flex flex-wrap items-center gap-1 text-[12px]">
        {visible.map((link, index) => (
          <span key={`${link.from}-${link.to}-${index}`} className="flex items-center gap-1">
            <span className="mono rounded-sm border border-border-soft px-1.5 py-0.5 text-text">
              {link.from}
            </span>
            <span className="text-faint" aria-hidden>
              →
            </span>
            {index === visible.length - 1 ? (
              <span className="mono rounded-sm border border-border-soft px-1.5 py-0.5 text-text">
                {link.to}
              </span>
            ) : null}
          </span>
        ))}
        {!expanded && transitions.length > 12 ? (
          <button
            type="button"
            className="text-[11.5px] text-accent hover:underline"
            onClick={() => setExpanded(true)}
          >
            ver todos ({transitions.length})
          </button>
        ) : null}
      </div>
    </div>
  );
}

function HypothesisList({ event }: { event: StoryEvent }) {
  const hypotheses = event.hypotheses;
  if (!hypotheses.length) return null;
  const supported = hypotheses.filter((item) => item.verdict === "SUPPORTED").length;
  const rejected = hypotheses.filter((item) => item.verdict === "REJECTED").length;
  const unresolved = hypotheses.filter((item) => item.verdict === "UNRESOLVED").length;
  return (
    <div className="mt-1.5 flex flex-col gap-2">
      <p className="text-[11.5px] text-muted">
        {supported} respaldada{supported === 1 ? "" : "s"} · {rejected} descartada
        {rejected === 1 ? "" : "s"}
        {unresolved ? ` · ${unresolved} sin resolver` : ""}
      </p>
      <ul className="flex flex-col gap-1.5">
        {hypotheses.map((hypothesis) => (
          <HypothesisCard key={hypothesis.id} hypothesis={hypothesis} />
        ))}
      </ul>
    </div>
  );
}

export function HypothesisCard({ hypothesis }: { hypothesis: StoryHypothesis }) {
  return (
    <li
      className="rounded-sm border border-border-soft px-2.5 py-2"
      data-verdict={hypothesis.verdict}
    >
      <div className="flex flex-wrap items-center gap-2">
        <span aria-hidden>{verdictGlyph(hypothesis.verdict)}</span>
        <span className="min-w-0 flex-1 text-[12.5px] text-text">{hypothesis.statement}</span>
        <Badge tone={verdictTone(hypothesis.verdict)}>{verdictLabel(hypothesis.verdict)}</Badge>
        {hypothesis.isUser ? <Badge tone="neutral">tu hipótesis</Badge> : null}
      </div>
      <div className="mt-1 flex flex-wrap gap-x-4 text-[11.5px] text-muted">
        {hypothesis.supporting ? <span>{hypothesis.supporting} evidencias a favor</span> : null}
        {hypothesis.contradicting ? (
          <span>{hypothesis.contradicting} evidencias en contra</span>
        ) : null}
        {hypothesis.missing.length ? (
          <span className="text-warn">
            falta: {hypothesis.missing.map((code) => code.toLowerCase()).join(", ")}
          </span>
        ) : null}
      </div>
    </li>
  );
}

function InferenceCard({ event }: { event: StoryEvent }) {
  const inference = (event.inference ?? {}) as Record<string, unknown>;
  const verdicts = Array.isArray(inference.verdicts)
    ? (inference.verdicts as Array<Record<string, unknown>>)
    : [];
  const failures = verdicts.filter((item) => String(item.verdict) !== "SUPPORTED");
  return (
    <div className="mt-1.5 flex flex-col gap-1 text-[11.5px] text-muted">
      <span>
        Premisas verificadas: <span className="mono text-text">{Number(inference.premises ?? 0)}</span>
      </span>
      {failures.length ? (
        <span className="text-warn">
          ⚠ Inferencia no demostrada: la conclusión no se desprende de los hechos
        </span>
      ) : (
        <span className="text-ok">✓ Inferencia respaldada</span>
      )}
    </div>
  );
}

function CompletionCard({ event }: { event: StoryEvent }) {
  const completion = (event.completion ?? {}) as Record<string, unknown>;
  const complete = completion.complete !== false;
  const reasons = eventReasonsText(event);
  return (
    <div
      className="mt-1.5 rounded-sm border border-border-soft px-2.5 py-2"
      data-state={complete ? "ok" : "warn"}
    >
      <p className="text-[11px] uppercase tracking-wide text-faint">Análisis</p>
      <p className={`mt-0.5 text-[12.5px] ${complete ? "text-ok" : "text-warn"}`}>
        {complete ? "ANÁLISIS COMPLETO ✓" : "ANÁLISIS INCOMPLETO ⚠"}
      </p>
      {!complete ? (
        <p className="mt-1 text-[11.5px] text-muted">
          Falta: {reasons || "evidencia crítica"}
        </p>
      ) : null}
    </div>
  );
}

export default ReasoningStory;
