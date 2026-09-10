// =============================================================================
// KnowledgeEntityCard — "What Zent Learned" (sección 20)
// =============================================================================
import { Graph, ListChecks, Question, Table } from "@phosphor-icons/react";
import type { LearnedEntity } from "../../lib/knowledgeLearning";
import { KnowledgeConfidenceBadge } from "./KnowledgeConfidenceBadge";

export function KnowledgeEntityCard({ entity }: { entity: LearnedEntity }) {
  const name = entity.display_name || entity.name;
  const coverage = entity.coverage_pct;
  return (
    <article
      className="panel animate-fade-in"
      data-testid={`entity-card-${entity.name}`}
    >
      <div className="flex items-start justify-between gap-2">
        <div className="min-w-0">
          <h3 className="truncate text-sm font-semibold uppercase tracking-wide text-text">
            {name}
          </h3>
          {entity.table && (
            <p className="mt-0.5 flex items-center gap-1 font-mono text-[11px] text-faint">
              <Table size={11} aria-hidden />
              {entity.table}
            </p>
          )}
        </div>
        <KnowledgeConfidenceBadge
          confidence={entity.confidence}
          label={entity.confidence_label}
        />
      </div>
      <p className="mt-2 line-clamp-3 min-h-[2.4rem] text-[13px] leading-relaxed text-muted">
        {entity.description || "Zent todavía no tiene una descripción de negocio."}
      </p>
      <dl className="mt-3 grid grid-cols-3 gap-2 text-[11px]">
        <div>
          <dt className="text-faint">Campos</dt>
          <dd className="font-medium tabular-nums text-text">
            {entity.fields_understood}/{entity.fields_total || entity.columns_total || "?"}
          </dd>
        </div>
        <div>
          <dt className="flex items-center gap-1 text-faint">
            <Graph size={11} aria-hidden /> Relaciones
          </dt>
          <dd className="font-medium tabular-nums text-text">
            {entity.relationships_confirmed}/{entity.relationships_total}
          </dd>
        </div>
        <div>
          <dt className="flex items-center gap-1 text-faint">
            <ListChecks size={11} aria-hidden /> Reglas
          </dt>
          <dd className="font-medium tabular-nums text-text">
            {entity.business_rules_approved}/{entity.business_rules_total}
          </dd>
        </div>
      </dl>
      {coverage !== null && (
        <div className="mt-3">
          <div className="flex items-center justify-between text-[11px] text-faint">
            <span>Cobertura de columnas</span>
            <span className="tabular-nums">{Math.round(coverage)}%</span>
          </div>
          <div className="progress-track mt-1 h-1">
            <div
              className={`h-full rounded-full ${
                coverage >= 80 ? "bg-ok" : coverage >= 50 ? "bg-accent" : "bg-warn"
              }`}
              style={{ width: `${Math.max(0, Math.min(100, coverage))}%` }}
            />
          </div>
        </div>
      )}
      {entity.open_questions > 0 && (
        <p className="mt-3 flex items-center gap-1 text-[12px] text-warn">
          <Question size={13} weight="fill" aria-hidden />
          {entity.open_questions} pregunta{entity.open_questions === 1 ? "" : "s"} pendiente
          {entity.open_questions === 1 ? "" : "s"}
        </p>
      )}
    </article>
  );
}
