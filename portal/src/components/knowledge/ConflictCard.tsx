// =============================================================================
// ConflictCard — dos fuentes dicen cosas distintas; decide un humano
// =============================================================================
import { Link } from "react-router-dom";
import { WarningCircle } from "@phosphor-icons/react";
import { Badge, cn } from "../ui";
import type { KnowledgeConflict } from "../../lib/knowledgeModel";
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
        {source || `Fuente ${tone.toUpperCase()}`}
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
  return (
    <article className={cn("kh-conflict", className)} data-testid="conflict-card">
      <header className="flex items-center gap-2">
        <WarningCircle size={14} className="shrink-0 text-warn" aria-hidden />
        <span className="min-w-0 flex-1 truncate text-sm text-text">
          {conflict.subject_label}
          {conflict.predicate ? ` · ${conflict.predicate}` : ""}
        </span>
        <Badge tone={conflict.status === "open" ? "warn" : "neutral"}>
          {conflict.status}
        </Badge>
      </header>
      <div className="mt-2 flex items-stretch gap-2">
        <Side value={conflict.value_a} source={conflict.source_a} tone="a" />
        <span className="self-center text-[11px] text-faint" aria-hidden>
          vs
        </span>
        <Side value={conflict.value_b} source={conflict.source_b} tone="b" />
      </div>
      <footer className="mt-2 flex items-center justify-between gap-2">
        <span className="text-[11px] text-faint">
          Detectado {fmtDateTime(conflict.detected_at)}
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
