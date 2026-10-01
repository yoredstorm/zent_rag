import type { ExecutionStory } from "../executionStory";
import type { ExecutionNarrative, NarrativeModelCall } from "../executionNarrative";
import JevLlmJourney from "./JevLlmJourney";
import ObservableReflection from "./ObservableReflection";

function Step({
  number,
  title,
  children,
}: {
  number: number;
  title: string;
  children: React.ReactNode;
}) {
  return (
    <li className="relative flex gap-3 pb-5 last:pb-0">
      <div className="flex shrink-0 flex-col items-center">
        <span className="flex h-6 w-6 items-center justify-center rounded-full border border-border bg-surface text-[11px] font-medium text-text">
          {number}
        </span>
        <span className="mt-1 h-full w-px bg-border-soft last:hidden" aria-hidden />
      </div>
      <section className="min-w-0 flex-1 pt-0.5">
        <h3 className="text-[13px] font-medium text-text">{title}</h3>
        <div className="mt-1.5 text-[12px] leading-5 text-muted">{children}</div>
      </section>
    </li>
  );
}

function Understanding({ narrative }: { narrative: ExecutionNarrative }) {
  const understanding = narrative.understanding;
  const anchors = [
    ...understanding.fields.map((value) => ({ label: "Campo", value })),
    ...understanding.rules.map((value) => ({ label: "Regla", value })),
    ...understanding.examples.map((value) => ({ label: "Ejemplo del usuario", value })),
  ];
  return (
    <>
      <p>
        {understanding.application ||
          understanding.observedSummary ||
          "Zent identificó el objetivo de la consulta antes de actuar."}
      </p>
      {anchors.length ? (
        <dl className="mt-2 grid grid-cols-1 gap-1.5 sm:grid-cols-2">
          {anchors.map((anchor) => (
            <div key={`${anchor.label}-${anchor.value}`} className="rounded border border-border-soft px-2 py-1.5">
              <dt className="text-[10.5px] text-faint">{anchor.label}</dt>
              <dd className="break-words text-[11.5px] text-text">{anchor.value}</dd>
            </div>
          ))}
        </dl>
      ) : null}
    </>
  );
}

function Requirements({ narrative }: { narrative: ExecutionNarrative }) {
  return (
    <>
      <p>Para responder, Zent separó lo que exigía una fuente del valor aportado por ti.</p>
      <ul className="mt-2 flex flex-col gap-1.5">
        {narrative.requirements.map((requirement) => (
          <li key={requirement.id} className="flex items-start gap-2">
            <span
              className={`mt-0.5 text-[11px] ${requirement.sourceRequired ? "text-ok" : "text-accent"}`}
              aria-hidden
            >
              {requirement.sourceRequired ? "✓" : "i"}
            </span>
            <span>
              <span className="text-text">{requirement.label}</span>
              <span className="ml-1 text-faint">
                {requirement.sourceRequired ? "Requiere fuente" : "Valor que se evaluó"}
              </span>
            </span>
          </li>
        ))}
      </ul>
    </>
  );
}

function Evidence({ narrative }: { narrative: ExecutionNarrative }) {
  const evidence = narrative.evidence;
  return (
    <>
      <p>
        {evidence.complete === true
          ? "Encontró respaldo para los requisitos documentales."
          : evidence.complete === false
            ? "Quedaron requisitos documentales pendientes."
            : "Consultó el conocimiento disponible."}
      </p>
      {evidence.documents.length ? (
        <details className="mt-2">
          <summary className="cursor-pointer text-accent">Ver fuentes</summary>
          <ul className="mt-2 flex flex-col gap-2">
            {evidence.documents.map((document) => (
              <li key={document.key} className="rounded border border-border-soft px-2.5 py-2">
                <p className="break-words font-medium text-text">{document.displayName}</p>
                <p className="text-[11px] text-faint">
                  {document.passageCount} fragmento{document.passageCount === 1 ? "" : "s"} utilizado{document.passageCount === 1 ? "" : "s"}
                </p>
                {document.passages.length ? (
                  <details className="mt-1 text-[11px]">
                    <summary className="cursor-pointer text-accent">Ver fragmentos</summary>
                    <ul className="mt-1.5 flex flex-col gap-1.5">
                      {document.passages.map((passage, index) => (
                        <li key={passage.evidenceId ?? `${document.key}-${index}`} className="text-muted">
                          {[passage.page != null ? `Página ${passage.page}` : "", passage.section]
                            .filter(Boolean)
                            .join(" · ")}
                          {passage.excerpt ? <p className="mt-0.5 text-faint">{passage.excerpt}</p> : null}
                        </li>
                      ))}
                    </ul>
                  </details>
                ) : null}
              </li>
            ))}
          </ul>
        </details>
      ) : null}
      <p className="mt-2 text-[11.5px] text-faint">
        {evidence.documentCount} documento{evidence.documentCount === 1 ? "" : "s"} aportaron {evidence.passageCount} fragmento{evidence.passageCount === 1 ? "" : "s"}.
      </p>
    </>
  );
}

function Judgment({ narrative }: { narrative: ExecutionNarrative }) {
  const count = narrative.summary.judgmentCount;
  const influenced = narrative.summary.decisionsInfluenced;
  return (
    <>
      <p>
        JEV hizo {count} {count === 1 ? "comprobación" : "comprobaciones"}.{" "}
        {influenced
          ? `${influenced} influyó en la ejecución.`
          : "Revisó el camino, pero no necesitó cambiarlo."}
      </p>
      {influenced ? (
        <p className="mt-1.5 text-text">JEV pidió ampliar la búsqueda y Zent aplicó esa decisión.</p>
      ) : null}
      {count ? (
        <details className="mt-2 rounded border border-border-soft px-2.5 py-2">
          <summary className="cursor-pointer text-accent">Ver las {count} comprobaciones</summary>
          <ObservableReflection narrative={narrative} />
        </details>
      ) : null}
    </>
  );
}

function Retry({ narrative }: { narrative: ExecutionNarrative }) {
  const complete = narrative.evidence.complete;
  return (
    <>
      <p>JEV pidió ampliar el respaldo. Zent ejecutó otra búsqueda.</p>
      <p className="mt-1.5 text-text">
        {complete === true
          ? "Después de ella no quedaron requisitos documentales pendientes."
          : complete === false
            ? "Después de ella todavía quedaron requisitos pendientes."
            : "El resultado de cobertura no quedó registrado en este run."}
      </p>
    </>
  );
}

const CALL_LABELS: Record<NarrativeModelCall["purpose"], string> = {
  ANALYSIS: "Analizó la evidencia recuperada",
  ANSWER: "Redactó la respuesta final",
  REVISION: "Corrigió la respuesta",
  UNKNOWN: "Procesó la evidencia",
};

function ModelCalls({ narrative }: { narrative: ExecutionNarrative }) {
  return (
    <>
      <ol className="flex flex-col gap-1">
        {narrative.modelCalls.map((call) => (
          <li key={call.id} className="flex gap-2">
            <span className="text-faint">{call.sequence}.</span>
            <span className="text-text">{CALL_LABELS[call.purpose]}</span>
          </li>
        ))}
      </ol>
      <p className="mt-1.5 text-[11.5px] text-faint">
        {narrative.modelCalls.length} llamada{narrative.modelCalls.length === 1 ? "" : "s"} al modelo. No añadió fuentes nuevas.
      </p>
    </>
  );
}

function Verification({ narrative }: { narrative: ExecutionNarrative }) {
  const verification = narrative.verification;
  const text =
    verification.overall === "verified"
      ? "La comprobación final terminó correctamente."
      : verification.overall === "partial"
        ? "La comprobación final fue parcial."
        : verification.overall === "blocked"
          ? "La comprobación final bloqueó la respuesta."
          : "No hay una comprobación final completa registrada.";
  return (
    <>
      <p>{text}</p>
      {verification.fallbackUsed ? (
        <p className="mt-1.5 text-text">
          La comprobación principal no estuvo disponible. Zent utilizó una validación alternativa.
        </p>
      ) : null}
      {verification.checks.length ? (
        <details className="mt-2">
          <summary className="cursor-pointer text-accent">Ver detalle de verificación</summary>
          <ul className="mt-1.5 flex flex-col gap-1">
            {verification.checks.map((check, index) => (
              <li key={`${String(check.key)}-${index}`} className="text-muted">
                {String(check.key ?? "Comprobación").replace(/_/g, " ")}: {String(check.state ?? "sin estado")}
              </li>
            ))}
          </ul>
        </details>
      ) : null}
    </>
  );
}

export function NarrativeSteps({ story }: { story: ExecutionStory }) {
  const narrative = story.executionNarrative;
  if (!narrative) return null;
  const hasRequirements = narrative.requirements.length > 0;
  const hasEvidence =
    narrative.evidence.documents.length > 0 || narrative.evidence.complete !== null;
  const hasJudgment = narrative.summary.judgmentCount > 0;
  const hasRetry = narrative.appliedDecisions.some((decision) =>
    ["retrieve_more", "search_knowledge"].includes(decision.action),
  );
  let number = 0;

  return (
    <div className="flex flex-col gap-4">
      <ol className="flex flex-col">
        <Step number={++number} title="Entendió tu consulta">
          <Understanding narrative={narrative} />
        </Step>
        {hasRequirements ? (
          <Step number={++number} title="Qué necesitaba comprobar">
            <Requirements narrative={narrative} />
          </Step>
        ) : null}
        {hasEvidence ? (
          <Step number={++number} title="Buscó respaldo en el conocimiento">
            <Evidence narrative={narrative} />
          </Step>
        ) : null}
        {hasJudgment ? (
          <Step number={++number} title="JEV revisó el camino">
            <Judgment narrative={narrative} />
          </Step>
        ) : null}
        {hasRetry ? (
          <Step number={++number} title="Buscó nuevamente">
            <Retry narrative={narrative} />
          </Step>
        ) : null}
        {narrative.modelCalls.length ? (
          <Step number={++number} title="El modelo resolvió el caso">
            <ModelCalls narrative={narrative} />
          </Step>
        ) : null}
        <Step number={number + 1} title="Verificación final">
          <Verification narrative={narrative} />
        </Step>
      </ol>
      <JevLlmJourney narrative={narrative} />
    </div>
  );
}

export default NarrativeSteps;
