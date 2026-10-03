// =============================================================================
// ConflictCard — conflicto interpretado: qué se comparó, con qué evidencia y
// por qué ZENT cree que puede ser real. Nunca "VALOR A / VALOR B / sin fuente".
// =============================================================================
import { Link } from "react-router-dom";
import { WarningCircle } from "@phosphor-icons/react";
import { Badge, cn } from "../ui";
import {
  conflictClassificationLabel,
  MATERIALITY_LABELS,
  type KnowledgeConflict,
} from "../../lib/knowledgeModel";
import { fmtDateTime } from "../../lib/format";

function Side({
  value,
  source,
  tone,
}: {
  value: string | null;
  source: string | null;
  tone: "a" | "b";
}) {
  return (
    <div className="min-w-0 flex-1 rounded-sm border border-border bg-raised/60 p-2">
      <p className="truncate text-xs text-text" title={value ?? undefined}>
        {value || "—"}
      </p>
      <p className="mt-0.5 truncate text-[11px] text-faint">
        {source ? `Fuente ${source}` : `Fuente ${tone.toUpperCase()} no determinada`}
      </p>
    </div>
  );
}

export function ConflictCard({
  conflict,
  className,
}: {
  conflict: KnowledgeConflict;
  className?: string;
}) {
  const classification = conflict.classification ?? null;
  const computedType =
    classification?.classification ?? conflict.conflict_type ?? null;
  const materiality = classification?.materiality ?? null;
  const confidence = classification?.confidence ?? null;
  const explanation = classification?.possible_explanation ?? conflict.reason ?? null;

  return (
    <article className={cn("kh-conflict", className)} data-testid="conflict-card">
      <header className="flex items-start gap-2">
        <WarningCircle size={14} className="mt-0.5 shrink-0 text-warn" aria-hidden />
        <div className="min-w-0 flex-1">
          <p className="text-[11px] uppercase tracking-wide text-faint">
            {conflictClassificationLabel(computedType)}
          </p>
          <p className="min-w-0 truncate text-sm text-text">
            {conflict.subject_label}
            {conflict.predicate ? ` · ${conflict.predicate}` : ""}
          </p>
        </div>
        <div className="flex shrink-0 flex-col items-end gap-1">
          <Badge tone={conflict.status === "open" ? "warn" : "neutral"}>
            {conflict.status}
          </Badge>
          {materiality ? (
            <span className="text-[10px] text-faint">
              {MATERIALITY_LABELS[materiality] ?? materiality}
            </span>
          ) : null}
        </div>
      </header>

      <div className="mt-2 flex items-stretch gap-2">
        <Side value={conflict.value_a} source={conflict.source_a} tone="a" />
        <span className="self-center text-[11px] text-faint" aria-hidden>
          vs
        </span>
        <Side value={conflict.value_b} source={conflict.source_b} tone="b" />
      </div>

      {explanation ? (
        <p className="mt-2 text-[11px] leading-relaxed text-muted">
          ZENT detectó: {explanation}
        </p>
      ) : null}

      <footer className="mt-2 flex items-center justify-between gap-2">
        <span className="text-[11px] text-faint">
          {confidence != null ? `Confianza ${Math.round(Number(confidence) * 100)}% · ` : ""}
          {classification?.source_independence === "independent_sources"
            ? "fuentes independientes · "
            : ""}
          {conflict.detected_at ? `detectado ${fmtDateTime(conflict.detected_at)}` : ""}
        </span>
        <Link
          to="/knowledge/health?tab=conflicts"
          className="text-[11px] text-accent hover:underline"
        >
          Revisar conflicto
        </Link>
      </footer>
    </article>
  );
}
