// =============================================================================
// Knowledge Domains — las áreas que ZENT ha aprendido
// =============================================================================
import { Link } from "react-router-dom";
import { ArrowRight, Graph } from "@phosphor-icons/react";
import { Panel, Skeleton, cn } from "../ui";
import type { KnowledgeDomain } from "../../lib/knowledgeModel";
import { timeAgo } from "../../lib/format";
import { ConflictBadge } from "./badges";

function coverageTone(pct: number): string {
  if (pct >= 70) return "bg-ok";
  if (pct >= 40) return "bg-warn";
  return "bg-danger";
}

export function KnowledgeDomains({
  domains,
  loading = false,
}: {
  domains: KnowledgeDomain[];
  loading?: boolean;
}) {
  const visible = domains.filter((domain) => domain.objects > 0);

  return (
    <Panel className="overflow-hidden" data-testid="knowledge-domains">
      <div className="panel-header">
        <div className="min-w-0">
          <h2 className="text-h3">Knowledge Domains</h2>
          <p className="mt-0.5 text-xs text-muted">
            Áreas que ZENT descubrió y sigue aprendiendo.
          </p>
        </div>
        <Link
          to="/knowledge/explorer"
          className="inline-flex items-center gap-1 text-xs text-accent hover:underline"
        >
          Explorar
          <ArrowRight size={12} aria-hidden />
        </Link>
      </div>

      <div className="panel-body">
        {loading && (
          <div className="flex flex-col gap-3" aria-busy="true">
            {[0, 1, 2].map((i) => (
              <Skeleton key={i} className="h-14 rounded-md" />
            ))}
          </div>
        )}

        {!loading && visible.length === 0 && (
          <p className="text-sm text-muted">
            Todavía no hay dominios con conocimiento. Cuando ZENT aprenda de una
            fuente, las áreas aparecerán aquí solas.
          </p>
        )}

        {!loading && visible.length > 0 && (
          <ul className="flex flex-col divide-y divide-border-soft">
            {visible.slice(0, 8).map((domain) => {
              const coverage =
                domain.objects > 0 ? (domain.verified / domain.objects) * 100 : 0;
              return (
                <li key={domain.name}>
                  <Link
                    to={`/knowledge/explorer?domain=${encodeURIComponent(domain.name)}`}
                    className="group flex flex-col gap-2 py-3 first:pt-0 last:pb-0"
                  >
                    <div className="flex flex-wrap items-center gap-2">
                      <span className="min-w-0 flex-1 truncate text-sm font-medium text-text">
                        {domain.name}
                      </span>
                      <span className="mono text-xs tabular-nums text-muted">
                        {domain.objects.toLocaleString("es-PE")} objetos
                      </span>
                      {(domain.edges ?? 0) > 0 && (
                        <span className="flex items-center gap-1 text-[11px] text-faint">
                          <Graph size={11} aria-hidden />
                          {domain.edges}
                        </span>
                      )}
                      <ConflictBadge count={domain.conflicts ?? 0} />
                      <ArrowRight
                        size={12}
                        className="text-ghost transition-transform group-hover:translate-x-0.5"
                        aria-hidden
                      />
                    </div>
                    <div className="flex items-center gap-3">
                      <span className="h-1 min-w-[80px] flex-1 overflow-hidden rounded-full bg-track">
                        <span
                          className={cn("block h-full rounded-full", coverageTone(coverage))}
                          style={{ width: `${Math.max(3, Math.min(100, coverage))}%` }}
                        />
                      </span>
                      <span className="text-[11px] text-faint">
                        {Math.round(coverage)}% verificado
                      </span>
                      {domain.avg_confidence != null && (
                        <span className="mono text-[11px] text-faint">
                          conf. {Math.round(domain.avg_confidence * 100)}%
                        </span>
                      )}
                      <span className="hidden text-[11px] text-faint sm:inline">
                        {domain.sources} fuente{domain.sources === 1 ? "" : "s"}
                      </span>
                      {domain.last_updated && (
                        <span className="hidden text-[11px] text-faint md:inline">
                          {timeAgo(domain.last_updated)}
                        </span>
                      )}
                    </div>
                  </Link>
                </li>
              );
            })}
          </ul>
        )}
      </div>
    </Panel>
  );
}
