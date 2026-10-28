// =============================================================================
// AttentionPanel — el conocimiento que necesita una decisión humana
// =============================================================================
import { Link } from "react-router-dom";
import { ArrowRight, CheckCircle, WarningCircle } from "@phosphor-icons/react";
import { Panel, cn } from "../ui";
import type {
  KnowledgeAttention,
  KnowledgeConflict,
  KnowledgeGap,
} from "../../lib/knowledgeModel";
import { priorityTone } from "../../lib/knowledgeModel";
import { ConflictCard } from "./ConflictCard";
import { loadSession } from "../../api";

export function AttentionPanel({
  attention,
  conflicts,
  gaps,
  measured = true,
}: {
  attention: KnowledgeAttention[];
  conflicts: KnowledgeConflict[];
  gaps: KnowledgeGap[];
  measured?: boolean;
}) {
  const empty = attention.length === 0 && conflicts.length === 0 && gaps.length === 0;
  const simple = Boolean(loadSession()?.featureFlags?.knowledge_simple_ux);

  return (
    <Panel className="overflow-hidden" data-testid="knowledge-attention">
      <div className="panel-header">
        <div className="min-w-0">
          <h2 className="text-h3">Necesita tu atención</h2>
          <p className="mt-0.5 text-xs text-muted">
            Problemas reales del conocimiento, con su acción.
          </p>
        </div>
        <Link
          to={simple ? "/knowledge/improve" : "/knowledge/health"}
          className="inline-flex items-center gap-1 text-xs text-accent hover:underline"
        >
          {simple ? "Ir a Mejorar" : "Ir a Salud"}
          <ArrowRight size={12} aria-hidden />
        </Link>
      </div>
      <div className="panel-body">
        {empty ? (
          <p className="flex items-start gap-2 text-sm text-muted">
            {measured ? (
              <CheckCircle size={15} className="mt-0.5 shrink-0 text-ok" aria-hidden />
            ) : (
              <WarningCircle size={15} className="mt-0.5 shrink-0 text-warn" aria-hidden />
            )}
            <span>
              {measured
                ? "No hay problemas medidos en este momento. Sigue revisando la evidencia antes de una tarea crítica."
                : "Todavía no hay mediciones suficientes para afirmar que el conocimiento está sano. No es lo mismo que cero problemas."}
            </span>
          </p>
        ) : (
          <div className="flex flex-col gap-4">
            {attention.length > 0 && (
              <ul className="flex flex-col gap-2">
                {attention.slice(0, 3).map((item) => (
                  <li key={`${item.kind}-${item.title}`}>
                    <Link
                      to={item.href}
                      className="flex items-center gap-2 text-sm text-text hover:underline"
                    >
                      <WarningCircle
                        size={14}
                        className={cn(
                          "shrink-0",
                          item.severity === "high" ? "text-danger" : "text-warn"
                        )}
                        aria-hidden
                      />
                      <span className="min-w-0 flex-1">{item.title}</span>
                      <ArrowRight size={12} className="shrink-0 text-ghost" aria-hidden />
                    </Link>
                  </li>
                ))}
              </ul>
            )}

            {conflicts.length > 0 && (
              <div className="flex flex-col gap-2">
                <p className="eyebrow">Conflictos abiertos</p>
                {conflicts.slice(0, 2).map((conflict) => (
                  <ConflictCard key={conflict.id} conflict={conflict} />
                ))}
              </div>
            )}

            {gaps.length > 0 && (
              <div>
                <p className="eyebrow mb-2">Vacíos de conocimiento</p>
                <ul className="flex flex-col gap-1.5">
                  {gaps.slice(0, 3).map((gap) => (
                    <li key={gap.id} className="flex items-center gap-2">
                      <span className={cn("badge shrink-0", priorityTone(gap.priority))}>
                        {gap.priority}
                      </span>
                      <span className="min-w-0 flex-1 truncate text-sm text-text">
                        {gap.title}
                      </span>
                    </li>
                  ))}
                </ul>
              </div>
            )}
          </div>
        )}
      </div>
    </Panel>
  );
}
