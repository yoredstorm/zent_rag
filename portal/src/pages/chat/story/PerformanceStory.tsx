// =============================================================================
// PerformanceStory — vista "Rendimiento" (§43-§47)
// =============================================================================
// Responde una sola pregunta: ¿por qué demoró lo que demoró?
//
// §44: la barra principal usa WALL-CLOCK real. La suma de spans puede superar
// ese total (solapamiento) y se declara, nunca se muestra como si fuera el total.
// Todo lo que no se observó simplemente no aparece.
import type { ExecutionStory } from "../executionStory";

function fmtMs(value: number): string {
  if (value <= 0) return "—";
  if (value >= 1000) return `${(value / 1000).toFixed(2)} s`;
  return `${value.toFixed(0)} ms`;
}

function share(ms: number, total: number): number {
  if (total <= 0) return 0;
  return Math.max(1, Math.round((ms / total) * 100));
}

export function PerformanceStory({ story }: { story: ExecutionStory }) {
  const performance = story.performance;
  const total = performance.totalMs;

  if (!total) {
    return (
      <div className="rounded-lg border border-border bg-surface p-4 text-[12.5px] text-muted">
        No hay telemetría de tiempos para este run.
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-4">
      <div className="rounded-lg border border-border bg-surface p-4">
        <p className="eyebrow">Por qué demoró {fmtMs(total)}</p>
        <ul className="mt-2 flex flex-col gap-2">
          {performance.segments.map((segment) => (
            <li key={segment.key} className="flex items-center gap-2 text-[12px]">
              <span className="w-48 shrink-0 truncate text-text">{segment.label}</span>
              <span className="h-1.5 flex-1 overflow-hidden rounded-full bg-surface-strong">
                <span
                  className="block h-full rounded-full bg-accent/70"
                  style={{ width: `${share(segment.ms, total)}%` }}
                  aria-hidden
                />
              </span>
              <span className="mono w-20 shrink-0 text-right tabular-nums text-faint">
                {fmtMs(segment.ms)}
              </span>
            </li>
          ))}
          {performance.unattributedMs > 0 ? (
            <li className="flex items-center gap-2 text-[12px]">
              <span className="w-48 shrink-0 truncate text-muted">Otros / coordinación</span>
              <span className="h-1.5 flex-1 overflow-hidden rounded-full bg-surface-strong">
                <span
                  className="block h-full rounded-full bg-muted/50"
                  style={{ width: `${share(performance.unattributedMs, total)}%` }}
                  aria-hidden
                />
              </span>
              <span className="mono w-20 shrink-0 text-right tabular-nums text-faint">
                {fmtMs(performance.unattributedMs)}
              </span>
            </li>
          ) : null}
        </ul>
        {performance.note ? (
          <p className="mt-2 text-[11.5px] text-faint">{performance.note}</p>
        ) : null}
      </div>

      {performance.llmCalls.length || performance.llmCallCount ? (
        <div className="rounded-lg border border-border bg-surface p-4">
          <p className="eyebrow">
            {performance.llmCallCount ?? performance.llmCalls.length} llamada
            {(performance.llmCallCount ?? performance.llmCalls.length) === 1 ? "" : "s"} al modelo
          </p>
          {performance.llmCalls.length ? (
            <ol className="mt-2 flex flex-col gap-1.5 text-[12px]">
              {performance.llmCalls.map((call) => (
                <li key={`${call.index}-${call.label}`} className="flex items-center gap-2">
                  <span className="mono w-5 shrink-0 text-faint">{call.index}.</span>
                  <span className="min-w-0 flex-1 truncate text-text">{call.label}</span>
                  {call.tokens ? (
                    <span className="mono shrink-0 tabular-nums text-faint">
                      {call.tokens} tokens
                    </span>
                  ) : null}
                  <span className="mono w-20 shrink-0 text-right tabular-nums text-muted">
                    {fmtMs(call.ms ?? 0)}
                  </span>
                </li>
              ))}
            </ol>
          ) : (
            <p className="mt-1 text-[11.5px] text-faint">
              El backend declaró el número de llamadas; el detalle por llamada no llegó en este run.
            </p>
          )}
        </div>
      ) : null}

      {performance.searches.length ? (
        <div className="rounded-lg border border-border bg-surface p-4">
          <p className="eyebrow">
            Conocimiento · {performance.searches.length} búsqueda
            {performance.searches.length === 1 ? "" : "s"}
          </p>
          <ul className="mt-2 flex flex-col gap-1.5 text-[12px]">
            {performance.searches.map((search) => (
              <li key={`${search.index}-${search.label}`} className="flex items-center gap-2">
                <span className="min-w-0 flex-1 truncate text-text">{search.label}</span>
                {search.chunks ? (
                  <span className="mono shrink-0 tabular-nums text-faint">
                    {search.chunks} fragmentos
                  </span>
                ) : null}
                <span className="mono w-20 shrink-0 text-right tabular-nums text-muted">
                  {fmtMs(search.ms ?? 0)}
                </span>
              </li>
            ))}
          </ul>
          {performance.uniqueEvidence ? (
            <p className="mt-2 text-[11.5px] text-faint">
              Evidencia única utilizada: {performance.uniqueEvidence}
            </p>
          ) : null}
        </div>
      ) : null}

      {performance.jevDecisions.length ? (
        <div className="rounded-lg border border-border bg-surface p-4">
          <p className="eyebrow">Juicio previo · {performance.jevDecisions.length} decisiones</p>
          <ul className="mt-2 flex flex-col gap-2 text-[12px]">
            {performance.jevDecisions.map((decision, index) => (
              <li key={`${decision.phaseLabel}-${index}`} className="flex flex-col gap-0.5">
                <div className="flex items-center gap-2">
                  <span className="mono w-5 shrink-0 text-faint">{index + 1}.</span>
                  <span className="min-w-0 flex-1 truncate text-text">{decision.label}</span>
                  {decision.confidence !== undefined ? (
                    <span className="mono shrink-0 tabular-nums text-muted">
                      conf. mín. {Math.round(decision.confidence * 100)}%
                    </span>
                  ) : null}
                  {decision.cached ? (
                    <span className="shrink-0 text-faint">reutilizada</span>
                  ) : null}
                </div>
                {decision.purpose ? (
                  <p className="pl-7 text-[11.5px] text-muted">{decision.purpose}</p>
                ) : null}
                {decision.uncertain ? (
                  <p className="pl-7 text-[11.5px] text-faint">
                    {decision.uncertain} juicio{decision.uncertain === 1 ? "" : "s"} con confianza
                    moderada
                  </p>
                ) : null}
              </li>
            ))}
          </ul>
        </div>
      ) : null}

      {performance.cumulativeSpanMs !== null ? (
        <details className="rounded-lg border border-border-soft px-3 py-2">
          <summary className="cursor-pointer text-[11.5px] text-accent">
            Trabajo acumulado de los spans
          </summary>
          <p className="mt-1.5 text-[11.5px] text-muted">
            {fmtMs(performance.cumulativeSpanMs)} de trabajo sumado, sobre {fmtMs(total)} de tiempo
            real.{" "}
            {performance.overlaps
              ? "Los spans se contienen entre sí: la suma no es el tiempo que esperó el usuario."
              : "Sin solapes detectados."}
          </p>
        </details>
      ) : null}
    </div>
  );
}

export default PerformanceStory;
