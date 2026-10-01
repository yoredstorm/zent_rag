// =============================================================================
// TraceV2Story — vista humana del Traceability Schema v2 (§17, §20, §25)
// =============================================================================
// Deriva TODO del trace canónico: titular, respaldo, journey, evidencia, JEV y
// diagnóstico. Progressive disclosure: primero la historia, después el detalle
// y al final el acceso a la vista técnica.
import { useState } from "react";
import { Badge, Tooltip } from "../../../components/ui";
import {
  DIMENSION_LABELS,
  JOURNEY_META,
  QUESTION_LABELS,
  CONSISTENCY_META,
  dimensionStatusMeta,
  diagnosticCopy,
  EXPLANATION_META,
  JUDGMENT_VALUE_LABELS,
  severityMeta,
} from "../traceabilityCatalog";
import {
  fmtMs,
  fmtPercent,
  fmtUsd,
  headlineFor,
  jevSummary,
  supportSummary,
  type TraceV2,
  type TraceV2DiagnosticItem,
  type TraceV2Document,
  type TraceV2Judgment,
  verificationSummary,
} from "../traceabilityV2";

export function TraceV2Story({
  trace,
  onOpenTechnical,
}: {
  trace: TraceV2;
  onOpenTechnical: () => void;
}) {
  const headline = headlineFor(trace);
  const metrics: Array<{ label: string; value: string; help?: string }> = [
    { label: "Respaldo", value: supportSummary(trace) },
    { label: "JEV", value: jevSummary(trace) },
    { label: "Verificación", value: verificationSummary(trace) },
    {
      label: "Tiempo",
      value: fmtMs(trace.timing.wallClockMs),
      help: "Tiempo real que esperó el usuario, de inicio a fin.",
    },
    {
      label: "Costo",
      value: fmtUsd(trace.cost.totalUsd),
      help: "Costo medido de la ejecución con los precios configurados.",
    },
  ];

  return (
    <div className="flex flex-col gap-5">
      <header className="rounded-lg border border-border bg-surface p-4">
        <div className="flex flex-wrap items-center gap-2">
          <h2 className="text-h2 text-text">{headline.title}</h2>
          <Badge tone={headline.tone}>{trace.upgradedFromSchema ? "Trazo histórico" : "Schema v2"}</Badge>
        </div>
        <p className="mt-1 text-[12.5px] text-muted">{headline.detail}</p>
        <dl className="mt-3 grid grid-cols-1 gap-x-4 gap-y-2 text-[12px] sm:grid-cols-2">
          {metrics.map((metric) => (
            <div key={metric.label}>
              <dt className="flex items-center gap-1 text-faint">
                {metric.label}
                {metric.help ? <Help label={metric.label} help={metric.help} /> : null}
              </dt>
              <dd className="text-text">{metric.value}</dd>
            </div>
          ))}
        </dl>
      </header>

      <section aria-label="Cómo llegó Zent a esta respuesta">
        <p className="eyebrow mb-2">Cómo llegó Zent a esta respuesta</p>
        <ol className="flex flex-col gap-2">
          {trace.presentation.journey.map((node) => {
            const meta = JOURNEY_META[node.kind];
            if (!meta) return null;
            return (
              <li
                key={node.id}
                className="flex gap-3 rounded-md border border-border-soft px-3 py-2"
              >
                <span className="mt-0.5 flex h-5 w-5 shrink-0 items-center justify-center rounded-full bg-surface-strong text-[11px] text-muted">
                  {node.sequence}
                </span>
                <div>
                  <p className="text-[12.5px] font-medium text-text">{meta.title}</p>
                  <p className="text-[12px] text-muted">{meta.body(node.params)}</p>
                </div>
              </li>
            );
          })}
        </ol>
      </section>

      <EvidenceSection trace={trace} />
      <JevSection trace={trace} />
      <ExplanationsSection trace={trace} />
      <DiagnosticsSection trace={trace} />

      <div>
        <button
          type="button"
          onClick={onOpenTechnical}
          className="rounded-sm border border-border px-3 py-1.5 text-[12px] text-text transition-colors duration-150 hover:bg-surface-strong"
        >
          Ver detalles técnicos
        </button>
      </div>
    </div>
  );
}

function Help({ label, help }: { label: string; help: string }) {
  return (
    <Tooltip label={help}>
      <button
        type="button"
        aria-label={`Qué significa ${label}`}
        className="inline-flex h-4 w-4 items-center justify-center rounded-full text-ghost hover:text-muted"
      >
        ?
      </button>
    </Tooltip>
  );
}

/* --- Evidencia ------------------------------------------------------------ */

function EvidenceSection({ trace }: { trace: TraceV2 }) {
  const counts = trace.counts;
  const [open, setOpen] = useState(false);
  if (!trace.documents.length && counts.evidenceRetrieved === null) return null;
  const retrieved = counts.evidenceRetrieved;
  const deduplicated = counts.evidenceDeduplicated;
  const unique = counts.evidenceUnique;
  const used = counts.evidenceUsed;
  const cited = counts.evidenceCited;
  return (
    <section aria-label="Evidencia utilizada">
      <button
        type="button"
        className="mb-2 flex w-full items-center justify-between gap-2 text-left"
        onClick={() => setOpen((value) => !value)}
        aria-expanded={open}
      >
        <span className="eyebrow">Evidencia utilizada</span>
        <span className="text-[11.5px] text-accent">{open ? "Ocultar" : "Mostrar"}</span>
      </button>
      <p className="mb-2 text-[12px] text-muted">
        {retrieved !== null
          ? `Se encontraron ${retrieved} fragmentos`
          : "Se recuperó evidencia"}
        {deduplicated ? `; ${deduplicated} eran duplicados o se solapaban` : ""}
        {unique !== null ? `; quedaron ${unique} evidencias únicas` : ""}
        {used !== null ? `, se usaron ${used}` : ""}
        {cited !== null ? ` y se citaron ${cited}.` : "."}
      </p>
      {open ? (
        <div className="flex flex-col gap-2">
          {trace.documents.map((document) => (
            <DocumentCard key={document.key || document.documentId || "doc"} document={document} />
          ))}
          {trace.diagnostics.items.some((item) => item.code === "SOURCE_NAME_MISSING") ? (
            <p className="text-[11.5px] text-faint">
              Hay fuentes sin nombre normalizado: se muestra una etiqueta reconstruida desde su
              identidad canónica. El detalle está en el diagnóstico.
            </p>
          ) : null}
        </div>
      ) : null}
    </section>
  );
}

function DocumentCard({ document }: { document: TraceV2Document }) {
  const name = document.displayName || document.name || "Fuente no identificada";
  return (
    <article className="rounded-md border border-border-soft px-3 py-2">
      <div className="flex flex-wrap items-center gap-2">
        <p className="text-[12.5px] font-medium text-text">{name}</p>
        {document.nameMissing ? (
          <Badge tone="warn">Nombre reconstruido</Badge>
        ) : null}
        <span className="text-[11px] text-faint">
          {document.evidenceCount} {document.evidenceCount === 1 ? "evidencia" : "evidencias"}
          {document.citedCount ? ` · ${document.citedCount} citada${document.citedCount === 1 ? "" : "s"}` : ""}
        </span>
      </div>
      <ul className="mt-1.5 flex flex-col gap-1.5">
        {document.items.map((item, index) => (
          <li key={item.evidenceId ?? `${document.key}-${index}`} className="text-[12px]">
            <div className="flex flex-wrap items-center gap-1.5 text-[11px] text-faint">
              {item.page !== null ? <span>pág. {item.page}</span> : null}
              {item.used ? <Badge tone="ok">Usada</Badge> : null}
              {item.cited ? <Badge tone="accent">Citada</Badge> : null}
              {item.mergedCount > 0 ? (
                <Tooltip
                  label={`Se fusionaron ${item.hitCount} fragmentos (${item.dedupKind ?? "duplicado"}).`}
                >
                  <span className="cursor-help underline decoration-dotted">
                    {item.hitCount} fragmentos fusionados
                  </span>
                </Tooltip>
              ) : null}
            </div>
            {item.excerpt ? (
              <p className="mt-0.5 text-muted">{item.excerpt}</p>
            ) : (
              <p className="mt-0.5 text-faint">El excerpt no está disponible en la telemetría.</p>
            )}
          </li>
        ))}
      </ul>
    </article>
  );
}

/* --- JEV ------------------------------------------------------------------ */

function JevSection({ trace }: { trace: TraceV2 }) {
  const [open, setOpen] = useState(false);
  if (!trace.jev.executed) return null;
  const material = trace.jev.decisions.filter((decision) => decision.material);
  const observational = trace.jev.decisions.filter((decision) => !decision.material);
  return (
    <section aria-label="Decisiones JEV">
      <button
        type="button"
        className="mb-2 flex w-full items-center justify-between gap-2 text-left"
        onClick={() => setOpen((value) => !value)}
        aria-expanded={open}
      >
        <span className="eyebrow">Decisiones JEV</span>
        <span className="text-[11.5px] text-accent">{open ? "Ocultar" : "Mostrar"}</span>
      </button>
      <p className="text-[12px] text-muted">{jevSummary(trace)}.</p>
      {open ? (
        <div className="mt-2 flex flex-col gap-2">
          {trace.jev.judgments.map((judgment) => (
            <JudgmentCard key={judgment.id} judgment={judgment} />
          ))}
          {material.length ? (
            <div>
              <p className="mb-1 text-[11px] font-medium tracking-wide text-faint">
                DECISIONES QUE CAMBIARON EL CAMINO
              </p>
              <ul className="flex flex-col gap-1">
                {material.map((decision) => (
                  <li key={decision.id} className="text-[12px] text-text">
                    {decision.action} · {decision.provider}
                    {decision.reasonCodes.length ? (
                      <span className="text-muted"> — {decision.reasonCodes.join(", ")}</span>
                    ) : null}
                  </li>
                ))}
              </ul>
            </div>
          ) : null}
          {observational.length ? (
            <p className="text-[11.5px] text-faint">
              {observational.length} decisión
              {observational.length === 1 ? "" : "es"} registrada
              {observational.length === 1 ? "" : "s"} sin efecto material (por ejemplo, confirmar
              la generación).
            </p>
          ) : null}
        </div>
      ) : null}
    </section>
  );
}

function JudgmentCard({ judgment }: { judgment: TraceV2Judgment }) {
  const [rawOpen, setRawOpen] = useState(false);
  const question = QUESTION_LABELS[judgment.questionCode] ?? judgment.questionCode;
  const answer =
    judgment.answer !== null
      ? (JUDGMENT_VALUE_LABELS[judgment.answer] ?? judgment.answer)
      : "Sin respuesta registrada";
  return (
    <article className="rounded-md border border-border-soft px-3 py-2">
      <p className="text-[12.5px] font-medium text-text">{question}</p>
      <p className="text-[12px] text-text">Resultado: {answer}</p>
      <p className="text-[11.5px] text-muted">
        {judgment.selectedProbability !== null ? (
          <>
            Probabilidad de la opción: {fmtPercent(judgment.selectedProbability)}
            {judgment.confidence !== null
              ? ` · Confianza derivada: ${fmtPercent(judgment.confidence)}`
              : ""}
          </>
        ) : judgment.certainty !== null ? (
          <>Certeza: {fmtPercent(judgment.certainty)}</>
        ) : (
          "Sin probabilidad registrada"
        )}
        {judgment.margin !== null ? ` · Margen: ${fmtPercent(judgment.margin)}` : ""}
      </p>
      <button
        type="button"
        className="mt-1 text-[11.5px] text-accent"
        onClick={() => setRawOpen((value) => !value)}
        aria-expanded={rawOpen}
      >
        {rawOpen ? "Ocultar datos crudos" : "Ver datos crudos"}
      </button>
      {rawOpen ? (
        <dl className="mt-1 grid grid-cols-2 gap-x-3 gap-y-1 text-[11px]">
          {judgment.options.length ? (
            <div className="col-span-2">
              <dt className="text-faint">Distribución</dt>
              <dd className="text-text">
                {judgment.options
                  .map(
                    (option) =>
                      `${option.key}: ${option.probability !== null ? fmtPercent(option.probability) : "—"}`,
                  )
                  .join(" · ")}
              </dd>
            </div>
          ) : null}
          {judgment.entropy !== null ? (
            <div>
              <dt className="text-faint">Entropía</dt>
              <dd className="text-text">{judgment.entropy.toFixed(3)}</dd>
            </div>
          ) : null}
          <div>
            <dt className="text-faint">Tipo</dt>
            <dd className="text-text">{judgment.type}</dd>
          </div>
          {judgment.effectCode ? (
            <div className="col-span-2">
              <dt className="text-faint">Efecto</dt>
              <dd className="text-text">{judgment.effectCode}</dd>
            </div>
          ) : null}
        </dl>
      ) : null}
    </article>
  );
}

/* --- Explicaciones contextuales (§22) ------------------------------------ */

function ExplanationsSection({ trace }: { trace: TraceV2 }) {
  const relevant = trace.presentation.explanations
    .map((item) => ({ item, meta: EXPLANATION_META[item.code] }))
    .filter((entry): entry is { item: typeof entry.item; meta: NonNullable<typeof entry.meta> } =>
      Boolean(entry.meta),
    );
  if (!relevant.length) return null;
  return (
    <section aria-label="Explicaciones de esta ejecución">
      <p className="eyebrow mb-2">Explicaciones de esta ejecución</p>
      <dl className="flex flex-col gap-2">
        {relevant.map(({ item, meta }) => (
          <div key={item.code} className="rounded-md border border-border-soft px-3 py-2">
            <dt className="text-[12.5px] font-medium text-text">{meta.question}</dt>
            <dd className="text-[12px] text-muted">{meta.answer(item.params)}</dd>
          </div>
        ))}
      </dl>
    </section>
  );
}

/* --- Diagnóstico ---------------------------------------------------------- */

function DiagnosticsSection({ trace }: { trace: TraceV2 }) {
  const dimensions = Object.entries(trace.diagnostics.dimensions).filter(
    ([key]) => DIMENSION_LABELS[key],
  );
  const consistency = CONSISTENCY_META[trace.diagnostics.consistency.status] ?? {
    label: trace.diagnostics.consistency.status,
    tone: "neutral" as const,
  };
  const verification = trace.verification.status;
  return (
    <section aria-label="Diagnóstico de la ejecución">
      <p className="eyebrow mb-2">Diagnóstico de la ejecución</p>
      <div className="grid grid-cols-1 gap-2 sm:grid-cols-2">
        {dimensions.map(([key, dimension]) => {
          const meta = dimensionStatusMeta(dimension.status);
          return (
            <div
              key={key}
              className="flex items-center justify-between gap-2 rounded-md border border-border-soft px-3 py-2"
            >
              <span className="text-[12px] text-muted">{DIMENSION_LABELS[key]}</span>
              <span className="flex items-center gap-1.5 text-[12px] text-text">
                <span aria-hidden>{meta.symbol}</span>
                {meta.label}
                {dimension.findings ? (
                  <span className="text-faint">({dimension.findings})</span>
                ) : null}
              </span>
            </div>
          );
        })}
      </div>
      <div className="mt-3 rounded-md border border-border-soft px-3 py-2 text-[12px]">
        <p className="text-text">
          Respuesta: <span className="text-muted">{verificationLabel(verification)}</span>
        </p>
        <p className="text-text">
          Trazabilidad: <Badge tone={consistency.tone}>{consistency.label}</Badge>
        </p>
        {trace.diagnostics.consistency.findings ? (
          <p className="mt-1 text-[11.5px] text-muted">
            {trace.diagnostics.consistency.findings} hallazgo
            {trace.diagnostics.consistency.findings === 1 ? "" : "s"} de telemetría; la calidad de la
            respuesta se evalúa por separado.
          </p>
        ) : null}
      </div>
      {trace.diagnostics.items.length ? (
        <div className="mt-2 flex flex-col gap-2">
          {trace.diagnostics.items.map((item) => (
            <DiagnosticCard key={`${item.code}-${JSON.stringify(item.params)}`} item={item} />
          ))}
        </div>
      ) : null}
    </section>
  );
}

function verificationLabel(status: string): string {
  if (status === "VERIFIED") return "Verificada";
  if (status === "PARTIALLY_VERIFIED") return "Verificada parcialmente";
  if (status === "CONFLICTING_EVIDENCE") return "Evidencia en conflicto";
  if (status === "INSUFFICIENT_EVIDENCE") return "Evidencia insuficiente";
  return "Sin verificar";
}

function DiagnosticCard({ item }: { item: TraceV2DiagnosticItem }) {
  const [open, setOpen] = useState(false);
  const copy = diagnosticCopy(item.code);
  const severity = severityMeta(item.severity);
  return (
    <article className="rounded-md border border-border-soft px-3 py-2">
      <button
        type="button"
        className="flex w-full items-center justify-between gap-2 text-left"
        onClick={() => setOpen((value) => !value)}
        aria-expanded={open}
      >
        <span className="text-[12.5px] font-medium text-text">{copy.title}</span>
        <Badge tone={severity.tone}>{severity.label}</Badge>
      </button>
      {open ? (
        <div className="mt-1.5 flex flex-col gap-1 text-[12px]">
          <p className="text-muted">
            <span className="text-faint">Qué significa: </span>
            {copy.meaning(item.params)}
          </p>
          <p className="text-muted">
            <span className="text-faint">¿Afectó la respuesta?: </span>
            {copy.impact(item.params)}
          </p>
          <p className="text-muted">
            <span className="text-faint">Qué debería corregirse: </span>
            {copy.fix(item.params)}
          </p>
          <p className="text-[11px] text-faint">
            Código técnico: <code>{item.code}</code>
            {item.materialEffect ? " · efecto material registrado" : ""}
          </p>
        </div>
      ) : null}
    </article>
  );
}

export default TraceV2Story;
