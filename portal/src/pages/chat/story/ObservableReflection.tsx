import type { ExecutionNarrative, NarrativeJudgment } from "../executionNarrative";
import ProbabilityDisplay from "./ProbabilityDisplay";

const QUESTION_LABELS: Record<string, string> = {
  needs_tool: "¿Necesitamos consultar conocimiento?",
  tool: "¿Qué fuente de información conviene usar?",
  needs_more_evidence: "¿Conviene buscar más evidencia?",
  satisfied: "¿Ya tenemos suficiente respaldo?",
  answer_ready: "¿La respuesta está lista para entregarse?",
};

const ANSWER_LABELS: Record<string, string> = {
  yes: "Sí",
  no: "No",
  uncertain: "Incierto",
  search_knowledge: "Conocimiento documental",
  none: "Ninguna opción clara",
  direct: "Responder directamente",
};

const BAND_LABELS: Record<string, string> = {
  low: "Certeza baja",
  medium: "Certeza media",
  high: "Certeza alta",
};

function answerLabel(value: unknown): string {
  const key = String(value ?? "");
  return ANSWER_LABELS[key] ?? (key.replace(/_/g, " ") || "Sin respuesta registrada");
}

function impactText(
  judgment: NarrativeJudgment,
  narrative: ExecutionNarrative,
): string {
  const decision = narrative.appliedDecisions.find(
    (item) => item.id === judgment.appliedDecisionId,
  );
  if (!decision) {
    return judgment.ambiguous
      ? "JEV no tuvo suficiente certeza para cambiar el camino."
      : "No se registró un cambio aplicado por esta comprobación.";
  }
  if (["retrieve_more", "search_knowledge"].includes(decision.action)) {
    return "Zent hizo una búsqueda adicional.";
  }
  return "La decisión se aplicó al camino de la ejecución.";
}

export function ObservableReflection({
  narrative,
}: {
  narrative: ExecutionNarrative;
}) {
  return (
    <div className="mt-2 flex flex-col divide-y divide-border-soft">
      {narrative.judgments.map((judgment) => (
        <article key={`${judgment.phase}-${judgment.id}`} className="py-3 first:pt-0">
          <p className="text-[12.5px] font-medium text-text">
            {QUESTION_LABELS[judgment.questionCode] ??
              judgment.questionCode.replace(/_/g, " ")}
          </p>
          <dl className="mt-1.5 grid grid-cols-1 gap-1 text-[11.5px] sm:grid-cols-2">
            <div>
              <dt className="text-faint">Respuesta</dt>
              <dd className="text-text">
                {answerLabel(judgment.answer)}
                {judgment.probability !== undefined ? (
                  <>
                    {" "}(
                    <ProbabilityDisplay value={judgment.probability} />)
                  </>
                ) : null}
              </dd>
            </div>
            {judgment.confidenceBand ? (
              <div>
                <dt className="text-faint">Certeza de la decisión</dt>
                <dd className="text-text">
                  {BAND_LABELS[judgment.confidenceBand] ?? judgment.confidenceBand}
                </dd>
              </div>
            ) : null}
          </dl>
          <p className="mt-1.5 text-[11.5px] text-muted">
            <span className="text-faint">Impacto: </span>
            {impactText(judgment, narrative)}
          </p>
          {judgment.alternatives.length > 1 ? (
            <details className="mt-1.5 text-[11px] text-muted">
              <summary className="cursor-pointer text-accent">Ver alternativas</summary>
              <ul className="mt-1 flex flex-col gap-0.5">
                {judgment.alternatives.map((alternative) => (
                  <li key={alternative.key} className="flex justify-between gap-4">
                    <span>{answerLabel(alternative.key)}</span>
                    <ProbabilityDisplay value={alternative.probability} />
                  </li>
                ))}
              </ul>
            </details>
          ) : null}
        </article>
      ))}
    </div>
  );
}

export default ObservableReflection;
