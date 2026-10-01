// =============================================================================
// Diagnóstico técnico — todo el contrato canónico, sin traducción
// =============================================================================
// Para administradores/desarrolladores: distribuciones crudas, decisiones
// observacionales, invariantes y gaps. La numeración/etiquetas humanas NO viven
// acá; esta vista muestra el dato tal como lo emitió el backend.
// =============================================================================

import { Badge } from "../../../components/ui";
import {
  displayConfidenceLabel,
  formatDisplayProbability,
  judgmentOutcomeLabel,
  type Traceability,
} from "../experience";

export function TraceabilityDiagnostics({ traceability }: { traceability: Traceability }) {
  const counts = traceability.counts;
  return (
    <div className="flex flex-col gap-4 text-[11.5px]">
      <section className="rounded-md border border-border px-3 py-2">
        <h3 className="mb-1.5 text-[11px] font-medium tracking-wide text-muted">
          TRAZABILIDAD CANÓNICA · schema {traceability.schemaVersion}
        </h3>
        <dl className="grid grid-cols-2 gap-x-3 gap-y-1 sm:grid-cols-3">
          {[
            ["documents_consulted", counts.documentsConsulted],
            ["documents_used", counts.documentsUsed],
            ["evidence_retrieved", counts.evidenceRetrieved],
            ["evidence_used", counts.evidenceUsed],
            ["evidence_cited", counts.evidenceCited ?? "—"],
          ].map(([label, value]) => (
            <div key={String(label)} className="contents">
              <dt className="text-faint">{label}</dt>
              <dd className="mono text-text">{String(value)}</dd>
            </div>
          ))}
        </dl>
      </section>

      {traceability.retrieval.rounds.length ? (
        <section className="rounded-md border border-border px-3 py-2">
          <h3 className="mb-1.5 text-[11px] font-medium tracking-wide text-muted">
            RONDAS DE RETRIEVAL
          </h3>
          <ul className="flex flex-col gap-1">
            {traceability.retrieval.rounds.map((round) => (
              <li key={round.attempt} className="flex flex-wrap items-center gap-2 text-muted">
                <span className="text-text">Ronda {round.attempt}</span>
                {round.strategy ? <span className="mono text-faint">{round.strategy}</span> : null}
                <Badge tone={round.sufficient === false ? "warn" : "ok"}>
                  {round.sufficient === false ? "insuficiente" : "suficiente"}
                </Badge>
                {round.evidence !== undefined ? (
                  <span>{round.evidence} evidencias</span>
                ) : null}
                {round.qualityScore !== undefined ? (
                  <span className="mono text-faint">score {round.qualityScore}</span>
                ) : null}
              </li>
            ))}
          </ul>
        </section>
      ) : null}

      <section className="rounded-md border border-border px-3 py-2">
        <h3 className="mb-1.5 text-[11px] font-medium tracking-wide text-muted">
          DECISIONES JEV (todas)
        </h3>
        {traceability.decisions.length ? (
          <ul className="flex flex-col gap-2">
            {traceability.decisions.map((decision) => (
              <li key={decision.id} className="border-b border-border-soft pb-2 last:border-none last:pb-0">
                <div className="flex flex-wrap items-center gap-2">
                  <span className="mono text-text">{decision.phase}</span>
                  <Badge
                    tone={
                      decision.classification === "BLOCKING"
                        ? "warn"
                        : decision.classification === "ACTIONABLE"
                          ? "ok"
                          : "neutral"
                    }
                  >
                    {decision.classification}
                  </Badge>
                  <span className="text-muted">
                    action={decision.action ?? "—"} applied={String(decision.applied)}
                  </span>
                  {decision.tier ? <span className="text-faint">tier={decision.tier}</span> : null}
                  {decision.display.probability !== undefined ? (
                    <span className="mono text-faint">
                      probability={decision.display.probability}
                    </span>
                  ) : null}
                </div>
                {decision.reasonCodes.length ? (
                  <p className="mono mt-0.5 text-faint">
                    reasons={decision.reasonCodes.join(",")}
                  </p>
                ) : null}
                {decision.effectCodes.length ? (
                  <p className="mono mt-0.5 text-faint">
                    effects={decision.effectCodes.join(",")}
                  </p>
                ) : null}
                {decision.beforeState || decision.afterState ? (
                  <p className="mono mt-0.5 text-faint">
                    before={JSON.stringify(decision.beforeState ?? {})} after=
                    {JSON.stringify(decision.afterState ?? {})}
                  </p>
                ) : null}
              </li>
            ))}
          </ul>
        ) : (
          <p className="text-faint">Sin decisiones registradas.</p>
        )}
      </section>

      <section className="rounded-md border border-border px-3 py-2">
        <h3 className="mb-1.5 text-[11px] font-medium tracking-wide text-muted">
          JUICIOS JEV (distribuciones crudas)
        </h3>
        {traceability.judgments.length ? (
          <ul className="flex flex-col gap-2">
            {traceability.judgments.map((judgment) => (
              <li key={judgment.id} className="border-b border-border-soft pb-2 last:border-none last:pb-0">
                <div className="flex flex-wrap items-center gap-2">
                  <span className="mono text-text">{judgment.id}</span>
                  <span className="text-faint">type={judgment.type}</span>
                  <span className="text-muted">
                    {judgmentOutcomeLabel(judgment.type, judgment.display) || "—"}
                  </span>
                  {judgment.display.probability !== undefined ? (
                    <span className="mono text-faint">
                      {formatDisplayProbability(judgment.display)}
                      {displayConfidenceLabel(judgment.display)
                        ? ` · ${displayConfidenceLabel(judgment.display)}`
                        : ""}
                    </span>
                  ) : null}
                  {judgment.effectCode ? (
                    <span className="mono text-faint">effect={judgment.effectCode}</span>
                  ) : null}
                </div>
                {judgment.alternatives.length ? (
                  <p className="mono mt-0.5 text-faint">
                    {judgment.alternatives
                      .map(
                        (alternative) =>
                          `${alternative.key}=${
                            alternative.probability === undefined
                              ? "—"
                              : alternative.probability.toFixed(4)
                          }`,
                      )
                      .join(" · ")}
                  </p>
                ) : null}
              </li>
            ))}
          </ul>
        ) : (
          <p className="text-faint">Sin juicios registrados.</p>
        )}
      </section>

      <section className="rounded-md border border-border px-3 py-2">
        <h3 className="mb-1.5 text-[11px] font-medium tracking-wide text-muted">
          VERIFICACIÓN (raw)
        </h3>
        <p className="mono text-text">status={traceability.verification.status}</p>
        <ul className="mt-1 flex flex-col gap-1">
          {traceability.verification.checks.map((check) => (
            <li key={check.key} className="flex flex-wrap gap-2 text-muted">
              <span className="mono text-text">{check.key}</span>
              <span>{check.state}</span>
              {check.detail ? <span className="mono text-faint">detail={check.detail}</span> : null}
              {check.source ? <span className="text-faint">source={check.source}</span> : null}
            </li>
          ))}
        </ul>
        <p className="mono mt-1 text-faint">
          signals={JSON.stringify(traceability.verification.signals)}
        </p>
      </section>

      {traceability.diagnostics.invariants.length || traceability.diagnostics.gaps.length ? (
        <section className="rounded-md border border-warn/40 px-3 py-2">
          <h3 className="mb-1.5 text-[11px] font-medium tracking-wide text-muted">
            INVARIANTES Y GAPS
          </h3>
          <ul className="flex flex-col gap-1">
            {traceability.diagnostics.invariants.map((item, index) => (
              <li key={`inv-${index}`} className="mono text-warn">
                invariant: {JSON.stringify(item)}
              </li>
            ))}
            {traceability.diagnostics.gaps.map((item, index) => (
              <li key={`gap-${index}`} className="mono text-faint">
                gap: {JSON.stringify(item)}
              </li>
            ))}
          </ul>
        </section>
      ) : null}
    </div>
  );
}

export default TraceabilityDiagnostics;
