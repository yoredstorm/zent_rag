// =============================================================================
// StoryCards — decisiones, evidencia y fuentes (§8-§12, §42-§43, §45)
// =============================================================================
// Traducen semántica a lenguaje humano. Nunca fabrican razones: si el evento no
// trae reason codes, no se muestra un "porque".
import { Badge, Progress, type Tone } from "../../../components/ui";
import { fmtCurrency } from "../../../lib/format";
import {
  authorityLabel,
  evidenceStatusLabel,
  reasonText,
  toJudgmentPacks,
  type StoryEvent,
} from "../executionStory";
import { JudgmentPackCard } from "./JudgmentStory";

function toneForStatus(status: string): Tone {
  const key = status.toUpperCase();
  if (key === "USED" || key === "KEEP") return "ok";
  if (key === "DISCARDED" || key === "DROP_IRRELEVANT") return "neutral";
  if (key === "DROP_WEAK" || key === "WEAK") return "warn";
  if (key === "CONTRADICTED" || key === "FLAG_CONTRADICTION") return "warn";
  if (key === "INJECTION_BLOCKED" || key === "DROP_INJECTION") return "danger";
  return "neutral";
}

export function StoryCard({ event, detailed }: { event: StoryEvent; detailed: boolean }) {
  switch (event.kind) {
    case "retrieval":
      return <RetrievalCard event={event} />;
    case "sources":
      return <SourcesCard event={event} detailed={detailed} />;
    case "sql":
      return <SqlCard event={event} />;
    case "generation":
      return <GenerationCard event={event} />;
    case "tool_call":
      return <ToolCard event={event} />;
    case "decision":
    case "tool_routing":
    case "tool_filter":
      return <DecisionCard event={event} />;
    case "jev_pack":
      return <JudgmentPackCardWrapper event={event} />;
    default:
      return null;
  }
}

/** §35: un pack JEV se muestra agrupado, no como tarjetas sueltas. */
function JudgmentPackCardWrapper({ event }: { event: StoryEvent }) {
  const [pack] = toJudgmentPacks([event]);
  if (!pack) return null;
  return <JudgmentPackCard pack={pack} />;
}

/** El nombre técnico de la herramienta acompaña a su título humano (§9, §39). */
function ToolCard({ event }: { event: StoryEvent }) {
  const tool = String(event.technical?.tool ?? "");
  if (!tool) return null;
  return (
    <div className="mt-1 flex flex-wrap items-center gap-x-3 text-[11.5px] text-muted">
      <span className="mono text-faint">{tool}</span>
      {event.status === "warn" ? <Badge tone="warn">requirió atención</Badge> : null}
    </div>
  );
}

function RetrievalCard({ event }: { event: StoryEvent }) {
  const chunks = number(event.metrics.chunks);
  const used = number(event.metrics.sources_used);
  const discarded = number(event.metrics.sources_discarded);
  return (
    <div className="mt-1 flex flex-wrap gap-x-4 gap-y-1 text-[11.5px] text-muted">
      {chunks ? <span>{chunks} fragmentos encontrados</span> : null}
      {used ? <span>{used} utilizados</span> : null}
      {discarded ? <span>{discarded} descartados</span> : null}
      {event.metrics.top_score !== undefined ? (
        <span className="mono">mejor score {Number(event.metrics.top_score).toFixed(2)}</span>
      ) : null}
    </div>
  );
}

function SourcesCard({ event, detailed }: { event: StoryEvent; detailed: boolean }) {
  const items = event.evidence.slice(0, detailed ? 16 : 6);
  const authority = (event.metrics.authority_counts ?? {}) as Record<string, number>;
  const authorities = Object.entries(authority).filter(([, count]) => count);
  if (!items.length) return null;
  return (
    <div className="mt-1.5">
      {authorities.length ? (
        <div className="mb-1.5 flex flex-wrap gap-1">
          {authorities.map(([level, count]) => (
            <Badge key={level} tone="neutral" title="Autoridad de la fuente configurada por el tenant">
              {authorityLabel(level)}: {count}
            </Badge>
          ))}
        </div>
      ) : null}
      <ul className="flex flex-col gap-1.5">
        {items.map((item) => (
          <li key={item.ref} className="text-[12px]">
            <div className="flex flex-wrap items-center gap-2">
              <span className="min-w-0 flex-1 truncate text-text">{item.title || item.ref}</span>
              {item.authority ? (
                <Badge tone="neutral">{authorityLabel(item.authority)}</Badge>
              ) : null}
              <Badge tone={toneForStatus(item.status)}>{evidenceStatusLabel(item.status)}</Badge>
              {item.relevance !== undefined ? (
                <span className="mono text-[11px] text-faint">
                  {(item.relevance * 100).toFixed(0)}%
                </span>
              ) : null}
            </div>
            {item.relevance !== undefined ? (
              <Progress value={Math.round(item.relevance * 100)} className="mt-1" />
            ) : null}
          </li>
        ))}
      </ul>
    </div>
  );
}

function SqlCard({ event }: { event: StoryEvent }) {
  const rows = number(event.metrics.rows);
  return (
    <div className="mt-1 flex flex-wrap gap-x-4 text-[11.5px] text-muted">
      {rows ? <span>{rows} filas</span> : null}
      {event.technical?.truncated ? <Badge tone="warn">resultado truncado</Badge> : null}
    </div>
  );
}

function GenerationCard({ event }: { event: StoryEvent }) {
  const tokens = number(event.metrics.total_tokens);
  const cost = number(event.metrics.cost_usd);
  const model = String(event.technical?.model ?? "");
  return (
    <div className="mt-1 flex flex-wrap gap-x-4 gap-y-1 text-[11.5px] text-muted">
      {model ? <span>{model}</span> : null}
      {tokens ? <span>{tokens} tokens</span> : null}
      {cost ? <span className="mono">{fmtCurrency(cost, 6)}</span> : null}
      <span className="text-faint">
        El modelo redactó una conclusión que ya estaba sustentada.
      </span>
    </div>
  );
}

/** §8: tarjeta de decisión con alternativas. El "porque" sólo si hay señal. */
function DecisionCard({ event }: { event: StoryEvent }) {
  const codes = event.decisionReasonCodes;
  const tool = String(event.technical?.tool ?? event.technical?.detail ?? "");
  const alternatives = ((event.technical?.alternatives as unknown[]) ?? []).filter(
    (item) => !!item && typeof item === "object",
  ) as Array<Record<string, unknown>>;
  return (
    <div className="mt-1.5 rounded-sm border border-border-soft bg-surface px-2.5 py-2">
      <p className="text-[11px] uppercase tracking-wide text-faint">Decisión</p>
      <p className="mt-0.5 text-[12.5px] text-text">{tool || event.title}</p>
      {codes.length ? (
        <div className="mt-1.5">
          <p className="text-[11.5px] text-muted">Porque:</p>
          <ul className="mt-0.5 list-disc pl-4 text-[11.5px] text-muted">
            {codes.map((code) => (
              <li key={code}>{reasonText(code)}</li>
            ))}
          </ul>
        </div>
      ) : null}
      {alternatives.length ? (
        <ul className="mt-1.5 flex flex-col gap-1 text-[11.5px] text-muted">
          {alternatives.map((alternative, index) => (
            <li key={`${String(alternative.name)}-${index}`} className="flex flex-wrap gap-1.5">
              <span className="text-text">
                {String(alternative.selected) === "true" ? "✓" : "○"}{" "}
                {String(alternative.name ?? "")}
              </span>
              <span className="text-faint">{String(alternative.detail ?? "")}</span>
            </li>
          ))}
        </ul>
      ) : null}
    </div>
  );
}

function number(value: unknown): number | undefined {
  const parsed = Number(value);
  return Number.isFinite(parsed) && parsed !== 0 ? parsed : undefined;
}

export default StoryCard;
