// =============================================================================
// TechnicalTrace — modo técnico para administradores (§32, §33, §45)
// =============================================================================
// Proveedor, JEV, scores, tokens, costos, ids y la traza cruda. No reemplaza la
// Story: la complementa.
import { CodeBlock } from "../../../components/ui";
import { fmtCurrency } from "../../../lib/format";
import type { ExecutionStory } from "../executionStory";

function fmtNumber(value: number | undefined | null, digits = 2): string {
  return value === undefined || value === null ? "—" : value.toFixed(digits);
}

/** §53: id, versión, primitiva, valor crudo y distribución de cada juicio. */
function JudgmentTechnical({ story }: { story: ExecutionStory }) {
  if (!story.judgmentPacks.length) return null;
  const blocks = story.judgmentPacks.filter((pack) => pack.judgments.length);
  if (!blocks.length) return null;
  return (
    <details>
      <summary className="cursor-pointer text-[11.5px] text-accent">
        Ver juicios previos (JEV)
      </summary>
      <div className="mt-2 flex flex-col gap-3">
        {blocks.map((pack) => (
          <div key={pack.id} className="rounded border border-border bg-surface/60 p-2">
            <p className="text-[11.5px] text-text">
              {pack.phase} · {pack.model ?? "sin modelo"} · {pack.judgmentCount} preguntas
              {pack.durationMs ? ` · ${Math.round(pack.durationMs)} ms` : ""}
              {pack.costUsd ? ` · ${fmtCurrency(pack.costUsd, 6)}` : ""}
              {pack.cached ? " · reutilizada" : ""}
            </p>
            <ul className="mt-1 flex flex-col gap-1 text-[11px] text-muted">
              {pack.judgments.map((judgment) => (
                <li key={judgment.id} className="mono flex flex-wrap gap-x-3 tabular-nums">
                  <span className="text-text">
                    {judgment.id}
                    {judgment.version ? ` v${judgment.version}` : ""}
                  </span>
                  <span>{judgment.type}</span>
                  <span>{judgment.decisionKey || "—"}</span>
                  {judgment.type === "noul" ? (
                    <>
                      <span>noul {fmtNumber(judgment.value, 4)}</span>
                      <span>certeza {fmtNumber(judgment.certainty, 4)}</span>
                    </>
                  ) : null}
                  {judgment.type === "score" ? <span>score {fmtNumber(judgment.value)}</span> : null}
                  {judgment.confidence !== undefined ? (
                    <span>conf {fmtNumber(judgment.confidence, 4)}</span>
                  ) : null}
                  {judgment.ambiguous ? <span>ambiguo</span> : null}
                  {judgment.distribution?.runner_up ? (
                    <span>
                      runner-up {String(judgment.distribution.runner_up)} (
                      {fmtNumber(Number(judgment.distribution.runner_up_probability), 4)})
                    </span>
                  ) : null}
                  {judgment.distribution?.margin !== undefined ? (
                    <span>margen {fmtNumber(Number(judgment.distribution.margin), 4)}</span>
                  ) : null}
                  {judgment.distribution?.entropy !== undefined ? (
                    <span>entropía {fmtNumber(Number(judgment.distribution.entropy), 4)}</span>
                  ) : null}
                </li>
              ))}
            </ul>
          </div>
        ))}
      </div>
    </details>
  );
}

export function TechnicalTrace({ story }: { story: ExecutionStory }) {
  const technical = story.technical;
  const rows: Array<[string, string]> = [];
  // §45: sólo se muestran datos conocidos. Missing != 0.
  if (story.runId) rows.push(["Run ID", story.runId]);
  const execution = technical.raw?.execution;
  if (execution && typeof execution === "object") {
    const kind = String((execution as Record<string, unknown>).kind ?? "");
    if (kind) rows.push(["Tipo de ejecución", kind]);
  }
  rows.push(["Flow version", String(story.version)]);
  rows.push([
    "Eventos canónicos / steps crudos",
    `${story.counts.canonicalEvents} / ${story.counts.rawSteps}`,
  ]);
  if (story.counts.unmapped) {
    rows.push([
      "Mapeados / sin mapping",
      `${story.counts.mapped} / ${story.counts.unmapped}`,
    ]);
  }
  if (technical.provider) rows.push(["Proveedor de decisión", technical.provider]);
  if (technical.decider) rows.push(["Decisor", technical.decider]);
  if (technical.model) rows.push(["Modelo", technical.model]);
  if (typeof story.llmCalls === "number") {
    rows.push(["Llamadas al modelo", String(story.llmCalls)]);
  }
  if (typeof technical.jevUsed === "boolean") {
    rows.push(["JEV", technical.jevUsed ? "intervino" : "no intervino"]);
  }
  if (technical.jevScore !== null && technical.jevScore !== undefined) {
    rows.push(["Score del gate de respuesta", technical.jevScore.toFixed(2)]);
  }
  if (technical.confidence !== null && technical.confidence !== undefined) {
    rows.push(["Confianza de decisión", technical.confidence.toFixed(2)]);
  }
  if (technical.tokens) {
    rows.push(["Tokens (prompt / completion)", `${technical.tokens.prompt} / ${technical.tokens.completion}`]);
    rows.push(["Tokens totales", String(technical.tokens.total)]);
  }
  if (story.totalMs) rows.push(["Latencia total", `${Math.round(story.totalMs)} ms`]);
  if (story.costUsd !== null) rows.push(["Costo", fmtCurrency(story.costUsd, 6)]);
  if (technical.pricing) {
    rows.push([
      "Precio del modelo (in / out por 1k)",
      `${fmtCurrency(Number(technical.pricing.input_cost_per_1k ?? 0), 6)} / ${fmtCurrency(
        Number(technical.pricing.output_cost_per_1k ?? 0),
        6,
      )}`,
    ]);
  }
  if (technical.answerability) {
    rows.push(["Answerability", JSON.stringify(technical.answerability)]);
  }
  rows.push(["Verificación", `${story.verification.label} (${story.verification.overall})`]);

  return (
    <div className="flex flex-col gap-3">
      <div>
        <p className="eyebrow mb-2">Traza técnica</p>
        <dl className="grid grid-cols-2 gap-x-4 gap-y-2 text-[12px]">
          {rows.map(([label, value]) => (
            <div key={label} className="min-w-0">
              <dt className="text-faint">{label}</dt>
              <dd className="truncate text-text" title={value}>
                {value}
              </dd>
            </div>
          ))}
        </dl>
      </div>
      <div>
        <p className="eyebrow mb-2">Observabilidad</p>
        <ul className="flex flex-col gap-1 text-[11.5px]">
          {story.telemetry.dimensions.map((dimension) => (
            <li key={dimension.key} className="flex items-center gap-2">
              <span className="w-40 shrink-0 text-faint">{dimension.label}</span>
              <span className={dimension.state === "observed" ? "text-ok" : "text-muted"}>
                {dimension.state}
              </span>
            </li>
          ))}
        </ul>
      </div>
      <JudgmentTechnical story={story} />
      <details>
        <summary className="cursor-pointer text-[11.5px] text-accent">Ver traza técnica</summary>
        <div className="mt-2">
          <CodeBlock
            code={JSON.stringify(technical.raw, null, 2)}
            language="json"
            maxHeight={320}
          />
        </div>
      </details>
    </div>
  );
}

export default TechnicalTrace;
