// =============================================================================
// TraceV2Technical — panel técnico autoexplicativo del schema v2 (§21, §22)
// =============================================================================
// Tarjetas semánticas, no un muro de key/value: cada dato con su explicación
// ("¿Qué significa esto?") y cada métrica con su escala declarada.
import type { ReactNode } from "react";
import { Badge, Tooltip } from "../../../components/ui";
import {
  CONSISTENCY_META,
  CONTROL_META,
  DIMENSION_LABELS,
  FALLBACK_CLASS_LABELS,
  METRIC_HELP,
  dimensionStatusMeta,
  severityMeta,
} from "../traceabilityCatalog";
import {
  fmtMs,
  fmtPercent,
  fmtUsd,
  headlineFor,
  type TraceV2,
} from "../traceabilityV2";

export function TraceV2Technical({ trace }: { trace: TraceV2 }) {
  const headline = headlineFor(trace);
  const consistency = CONSISTENCY_META[trace.diagnostics.consistency.status] ?? {
    label: trace.diagnostics.consistency.status,
    tone: "neutral" as const,
  };
  return (
    <div className="flex flex-col gap-3">
      <div className="flex flex-wrap items-center gap-2">
        <p className="eyebrow">TRAZABILIDAD CANÓNICA · schema {trace.schemaVersion}</p>
        <Badge tone={headline.tone}>{headline.title}</Badge>
        {trace.upgradedFromSchema ? (
          <Badge tone="info">Adaptado de schema {trace.upgradedFromSchema}</Badge>
        ) : null}
      </div>

      <Card title="EJECUCIÓN">
        <Row label="Tipo" value={trace.execution.kind ?? "—"} />
        <Row label="Id" value={trace.execution.id ?? "—"} mono />
        <Row label="Estado" value={trace.execution.status ?? "—"} />
        <Row label="Respuesta entregada" value={yesNo(trace.execution.delivered)} />
        <Row label="Método" value={trace.execution.method ?? "—"} />
        {trace.execution.question ? (
          <Row label="Pregunta" value={trace.execution.question} />
        ) : null}
        <Row label="Ruta" value={trace.routing.route ?? "—"} />
        <Row label="Decisor" value={trace.routing.decider ?? "—"} />
        {trace.routing.confidence !== null ? (
          <Row
            label="Confianza de ruta"
            value={fmtPercent(trace.routing.confidence)}
            help="Confianza derivada de la decisión de ruta; no es una probabilidad de respuesta."
          />
        ) : null}
      </Card>

      <Card title="CONOCIMIENTO">
        <Row label="Estrategia" value={trace.knowledge.strategy ?? trace.knowledge.engineStrategy ?? "—"} />
        <Row label="Rondas" value={String(trace.retrieval.rounds.length || trace.retrieval.attempts || "—")} />
        <Row label="Búsqueda ampliada" value={yesNo(trace.retrieval.expanded)} />
        <Row label="Fragmentos" value={value(trace.knowledge.chunks)} />
        <Row
          label="Mejor score"
          value={trace.knowledge.topScore !== null ? trace.knowledge.topScore.toFixed(4) : "—"}
          help={METRIC_HELP.score.description}
        />
        {typeof trace.knowledge.representation.document_understanding === "string" ? (
          <Row
            label="Comprensión documental"
            value={String(trace.knowledge.representation.document_understanding)}
          />
        ) : null}
      </Card>

      <Card title="EVIDENCIA">
        <Row label="Documentos recuperados" value={value(trace.counts.documentsRetrieved)} />
        <Row label="Documentos usados" value={value(trace.counts.documentsUsed)} />
        <Row label="Fragmentos recuperados" value={value(trace.counts.evidenceRetrieved)} />
        <Row
          label="Duplicados fusionados"
          value={value(trace.counts.evidenceDeduplicated)}
          help="Fragmentos que representaban la misma evidencia lógica (duplicado exacto, solape de chunking o similitud fuerte)."
        />
        <Row label="Evidencias únicas" value={value(trace.counts.evidenceUnique)} />
        <Row label="Seleccionadas" value={value(trace.counts.evidenceSelected)} />
        <Row label="Usadas" value={value(trace.counts.evidenceUsed)} />
        <Row label="Citadas" value={value(trace.counts.evidenceCited)} />
        {trace.citationsSummary.references !== null ? (
          <Row
            label="Referencias de cita"
            value={`${trace.citationsSummary.references} (${
              trace.citationsSummary.uniqueCited ?? 0
            } únicas${
              trace.citationsSummary.collapsed
                ? `, ${trace.citationsSummary.collapsed} repetidas`
                : ""
            })`}
            help="Una cita repetida apunta a la misma evidencia. El conteo de evidencias citadas usa ids únicos."
          />
        ) : null}
        {trace.collection === "partial" ? (
          <Row
            label="Detalle"
            value="Parcial: el runtime declaró más fragmentos que los expuestos."
            help="Los conteos únicos no se calculan cuando el detalle está truncado; no se inventan."
          />
        ) : null}
      </Card>

      <Card title="JEV">
        <Row label="Ejecutado" value={yesNo(trace.jev.executed)} />
        <Row label="Modo" value={trace.jev.mode ?? "—"} />
        <Row label="Llamadas" value={value(trace.jev.calls)} />
        <Row label="Comprobaciones" value={value(trace.jev.checks)} />
        <Row
          label="Intervención material"
          value={
            trace.jev.materialIntervention
              ? "Sí: cambió o bloqueó una decisión"
              : "No: confirmó el camino"
          }
          help="Ejecutar JEV no es intervenir. Una confirmación (por ejemplo, generar) no cuenta como intervención."
        />
        <Row label="Cambió la ruta" value={yesNo(trace.jev.changedRoute)} />
        <Row label="Pidió más evidencia" value={yesNo(trace.jev.requestedMoreEvidence)} />
        <Row label="Bloqueó la generación" value={yesNo(trace.jev.blockedGeneration)} />
        {trace.jev.latencyMs !== null ? <Row label="Latencia JEV" value={fmtMs(trace.jev.latencyMs)} /> : null}
        {trace.jev.judgments.length ? (
          <div className="mt-2 col-span-2 flex flex-col gap-1">
            <p className="text-[11px] font-medium tracking-wide text-faint">JUICIOS (INTERPRETADO)</p>
            {trace.jev.judgments.map((judgment) => (
              <p key={judgment.id} className="text-[12px] text-muted">
                {judgment.questionCode}: {judgment.answer ?? "—"}
                {judgment.selectedProbability !== null
                  ? ` · probabilidad ${fmtPercent(judgment.selectedProbability)}`
                  : ""}
                {judgment.confidence !== null
                  ? ` · confianza derivada ${fmtPercent(judgment.confidence)}`
                  : ""}
                {judgment.entropy !== null ? ` · entropía ${judgment.entropy.toFixed(3)}` : ""}
              </p>
            ))}
          </div>
        ) : null}
      </Card>

      <Card title="GENERACIÓN">
        <Row label="Modelo" value={trace.generation.model ?? "—"} />
        <Row label="Llamadas" value={value(trace.generation.calls)} />
        <Row
          label="Generación de respuesta"
          value={value(trace.generation.answerCalls)}
          help="Llamadas cuyo propósito fue redactar la respuesta final."
        />
        <Row label="Razonamiento" value={value(trace.generation.reasoningCalls)} />
        {trace.generation.revisionCalls ? (
          <Row label="Revisiones" value={value(trace.generation.revisionCalls)} />
        ) : null}
        <Row
          label="Tokens"
          value={
            trace.generation.tokens.total !== null
              ? `${value(trace.generation.tokens.input)} entrada · ${value(
                  trace.generation.tokens.output,
                )} salida · ${trace.generation.tokens.total} total`
              : "—"
          }
        />
        <Row label="Tiempo del modelo" value={fmtMs(trace.generation.durationMs)} />
        <Row label="Costo" value={fmtUsd(trace.generation.costUsd)} />
        {trace.generation.finishReason ? (
          <Row label="finish_reason" value={trace.generation.finishReason} mono />
        ) : null}
        {trace.generation.callsDetail.length ? (
          <div className="mt-2 col-span-2 flex flex-col gap-1">
            <p className="text-[11px] font-medium tracking-wide text-faint">LLAMADAS POR PROPÓSITO</p>
            {trace.generation.callsDetail.map((call) => (
              <p key={call.id} className="text-[12px] text-muted">
                {call.sequence}. {purposeLabel(call.purpose)}
                {call.model ? ` · ${call.model}` : ""}
                {call.durationMs !== null ? ` · ${fmtMs(call.durationMs)}` : ""}
              </p>
            ))}
          </div>
        ) : null}
      </Card>

      <Card title="VERIFICACIÓN">
        <Row label="Estado" value={verificationLabel(trace.verification.status)} />
        <Row label="Grounding" value={yesNo(trace.verification.grounded)} />
        <Row label="Fallback del verificador" value={yesNo(trace.verification.fallbackUsed)} />
        {trace.verification.fallbackCode ? (
          <Row label="Código de fallback" value={trace.verification.fallbackCode} mono />
        ) : null}
        <Row
          label="Efecto material"
          value={yesNo(trace.verification.materialFallback)}
          help="Indica si el fallback cambió el resultado, no si ocurrió."
        />
        {trace.verification.quality !== null ? (
          <Row
            label="Calidad del gate"
            value={trace.verification.quality.toFixed(2)}
            help={METRIC_HELP.quality.description}
          />
        ) : null}
        {trace.verification.checks.length ? (
          <div className="mt-2 col-span-2 flex flex-col gap-1">
            <p className="text-[11px] font-medium tracking-wide text-faint">COMPROBACIONES</p>
            {trace.verification.checks.map((check) => (
              <p key={check.key} className="text-[12px] text-muted">
                {check.key}: {check.state}
                {check.detail ? ` (${check.detail})` : ""}
              </p>
            ))}
          </div>
        ) : null}
        {trace.verification.degradations.length ? (
          <div className="mt-2 col-span-2 flex flex-col gap-1">
            <p className="text-[11px] font-medium tracking-wide text-faint">DEGRADACIONES</p>
            {trace.verification.degradations.map((degradation) => (
              <p key={degradation.code} className="text-[12px] text-muted">
                {degradation.code}: {degradation.impact}
              </p>
            ))}
          </div>
        ) : null}
      </Card>

      <Card title="TIEMPOS">
        <Row
          label="Tiempo real percibido"
          value={fmtMs(trace.timing.wallClockMs)}
          help={METRIC_HELP.wall_clock_ms.description}
        />
        <Row
          label="Trabajo interno acumulado"
          value={fmtMs(trace.timing.accumulatedMs)}
          help={METRIC_HELP.accumulated_ms.description}
        />
        <Row
          label="Operaciones en paralelo"
          value={
            trace.timing.parallel === true
              ? "Sí (la suma puede superar el tiempo real)"
              : trace.timing.parallel === false
                ? "No"
                : "—"
          }
        />
        {trace.timing.breakdown.map((part) => (
          <Row key={part.code} label={timingLabel(part.code)} value={fmtMs(part.ms)} />
        ))}
      </Card>

      <Card title="COSTO">
        <Row label="Total" value={fmtUsd(trace.cost.totalUsd)} />
        {trace.cost.breakdown.map((part) => (
          <Row key={part.code} label={part.code} value={fmtUsd(part.usd)} />
        ))}
      </Card>

      <Card title="FALLBACKS Y RECUPERACIÓN">
        {trace.controls.length ? (
          trace.controls.map((control) => {
            const meta = CONTROL_META[control.controlCode];
            return (
              <div key={control.controlCode} className="col-span-2 rounded-sm border border-border-soft px-2.5 py-2">
                <div className="flex flex-wrap items-center gap-2">
                  <p className="text-[12.5px] font-medium text-text">
                    {meta?.title ?? control.controlCode}
                  </p>
                  <Badge tone={severityMeta(control.severity).tone}>
                    {severityMeta(control.severity).label}
                  </Badge>
                </div>
                {meta ? (
                  <div className="mt-1 flex flex-col gap-0.5 text-[12px] text-muted">
                    <p>Qué ocurrió: {meta.happened}</p>
                    <p>Qué hizo Zent: {meta.action}</p>
                    <p>Estado: {meta.state(control.params, control.recovered)}</p>
                    <p>
                      Impacto:{" "}
                      {control.materialEffect
                        ? "material (la respuesta pudo cambiar)"
                        : "ninguno detectado"}
                    </p>
                  </div>
                ) : null}
              </div>
            );
          })
        ) : (
          <Row label="Controles" value="No se activó ningún control." />
        )}
        {trace.fallbacks.events.length ? (
          <div className="mt-1 col-span-2 flex flex-col gap-1">
            <p className="text-[11px] font-medium tracking-wide text-faint">EVENTOS DE FALLBACK</p>
            {trace.fallbacks.events.map((event) => (
              <p key={event.code} className="text-[12px] text-muted">
                {event.code}: {FALLBACK_CLASS_LABELS[event.fallbackClass] ?? event.fallbackClass}
                {event.materialEffect ? " · efecto material" : ""}
              </p>
            ))}
          </div>
        ) : null}
      </Card>

      <Card title="CALIDAD DE TELEMETRÍA">
        <Row
          label="Consistencia"
          value={<Badge tone={consistency.tone}>{consistency.label}</Badge>}
          help="Evalúa la higiene del trace: no es la calidad de la respuesta."
        />
        <Row
          label="Calidad de la respuesta"
          value={verificationLabel(trace.diagnostics.consistency.responseQuality ?? trace.verification.status)}
          help="La respuesta se evalúa por su verificación, no por los problemas de observabilidad."
        />
        {Object.entries(trace.diagnostics.dimensions).map(([key, dimension]) => (
          <Row
            key={key}
            label={DIMENSION_LABELS[key] ?? key}
            value={`${dimensionStatusMeta(dimension.status).symbol} ${
              dimensionStatusMeta(dimension.status).label
            }`}
          />
        ))}
      </Card>
    </div>
  );
}

function Card({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section className="rounded-md border border-border px-3 py-2">
      <h3 className="mb-1.5 text-[11px] font-medium tracking-wide text-muted">{title}</h3>
      <dl className="grid grid-cols-1 gap-x-4 gap-y-1 sm:grid-cols-2">{children}</dl>
    </section>
  );
}

function Row({
  label,
  value,
  help,
  mono,
}: {
  label: string;
  value: ReactNode;
  help?: string;
  mono?: boolean;
}) {
  return (
    <div className="contents">
      <dt className="flex items-center gap-1 text-[12px] text-faint">
        {label}
        {help ? (
          <Tooltip label={help}>
            <button
              type="button"
              aria-label={`Qué significa ${label}`}
              className="inline-flex h-4 w-4 items-center justify-center rounded-full text-ghost hover:text-muted"
            >
              ?
            </button>
          </Tooltip>
        ) : null}
      </dt>
      <dd className={`text-[12px] text-text ${mono ? "font-mono" : ""}`}>{value}</dd>
    </div>
  );
}

function value(input: number | null): string {
  return input === null ? "—" : String(input);
}

function yesNo(input: boolean | null): string {
  if (input === null) return "—";
  return input ? "Sí" : "No";
}

function verificationLabel(status: string): string {
  if (status === "VERIFIED") return "Verificada";
  if (status === "PARTIALLY_VERIFIED") return "Verificada parcialmente";
  if (status === "CONFLICTING_EVIDENCE") return "Evidencia en conflicto";
  if (status === "INSUFFICIENT_EVIDENCE") return "Evidencia insuficiente";
  if (status === "UNVERIFIED") return "Sin verificar";
  return status;
}

function purposeLabel(purpose: string): string {
  const labels: Record<string, string> = {
    reasoning: "Razonamiento",
    tool_decision: "Decisión de herramienta",
    answer_generation: "Generación de la respuesta",
    revision: "Revisión",
    verification: "Verificación",
    unknown: "Propósito no observado",
  };
  return labels[purpose] ?? purpose;
}

function timingLabel(code: string): string {
  const labels: Record<string, string> = {
    model: "Modelo",
    tools: "Herramientas",
    gates: "Gates",
    retrieval: "Búsqueda",
    evidence: "Evidencia",
    verification: "Verificación",
    routing: "Decisión de ruta",
    planning: "Planificación",
    sql: "SQL",
    context: "Contexto",
    unattributed: "No atribuido",
    other: "Otros / coordinación",
  };
  return labels[code] ?? code;
}

export default TraceV2Technical;
