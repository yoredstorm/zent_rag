// =============================================================================
// KnowledgeMatches — ZENT encontró conocimiento que ya existía
// =============================================================================
// Cada "reencuentro" es un evento real (ENTITY_MATCHED / ENTITY_MERGED). Los
// contadores de refuerzo son del delta de la sesión: aprendizaje incremental,
// no una carga que empieza de cero.
// =============================================================================
import { GitMerge, LinkSimple } from "@phosphor-icons/react";

import { timeAgo } from "../../lib/format";
import { AnimatedNumber } from "./KnowledgePulse";
import type { KnowledgeMatch } from "./learningInsights";

export function KnowledgeMatches({
  matches,
  matched,
  merged,
  reinforced,
  enriched,
}: {
  matches: KnowledgeMatch[];
  matched: number;
  merged: number;
  reinforced: number;
  enriched: number;
}) {
  if (matched === 0 && merged === 0) return null;

  return (
    <section className="panel ks-matches" data-testid="knowledge-matches">
      <header className="panel-header">
        <div className="min-w-0">
          <p className="eyebrow">Conocimiento existente</p>
          <h2 className="text-h3">ZENT reconoció lo que ya sabía</h2>
        </div>
      </header>
      <div className="panel-body flex flex-col gap-3">
        <p className="text-[13px] leading-relaxed text-muted">
          <strong className="text-text">
            <AnimatedNumber value={matched} />
          </strong>{" "}
          {matched === 1 ? "concepto ya conocido se encontró" : "conceptos ya conocidos se encontraron"}{" "}
          con esta carga y{" "}
          <strong className="text-text">
            <AnimatedNumber value={reinforced} />
          </strong>{" "}
          {reinforced === 1
            ? "hecho recibió nuevo respaldo"
            : "hechos recibieron nuevo respaldo"}
          .{" "}
          <strong className="text-text">
            <AnimatedNumber value={merged} />
          </strong>{" "}
          {merged === 1
            ? "duplicado se consolidó"
            : "duplicados se consolidaron"}{" "}
          en su nodo existente
          {enriched > 0 && (
            <>
              {" "}
              y <strong className="text-text">
                <AnimatedNumber value={enriched} />
              </strong>{" "}
              {enriched === 1
                ? "concepto se enriqueció"
                : "conceptos se enriquecieron"}
            </>
          )}
          .
        </p>

        {matches.length > 0 && (
          <ul className="ks-match-list">
            {matches.slice(0, 8).map((match) => (
              <li key={match.id} className="ks-match">
                <span className="ks-match-icon" aria-hidden>
                  {match.kind === "merged" ? (
                    <GitMerge size={13} weight="bold" className="text-info" />
                  ) : (
                    <LinkSimple size={13} weight="bold" className="text-info" />
                  )}
                </span>
                <span className="min-w-0 flex-1">
                  <span className="block truncate text-[13px] text-text">
                    {match.name}
                    {match.canonical && (
                      <span className="text-faint"> → {match.canonical}</span>
                    )}
                  </span>
                  <span className="text-[11px] text-faint">
                    {match.kind === "merged" ? "consolidado" : "ya conocido"}
                    {match.entityType ? ` · ${match.entityType}` : ""}
                  </span>
                </span>
                {match.at && (
                  <time className="text-[11px] text-faint" dateTime={match.at}>
                    {timeAgo(match.at)}
                  </time>
                )}
              </li>
            ))}
          </ul>
        )}
      </div>
    </section>
  );
}

export default KnowledgeMatches;
