// =============================================================================
// AgentKnowledgeSection — CONOCIMIENTO de alto nivel.
// =============================================================================
// El usuario elige QUÉ información puede usar el agente. CÓMO consultarla
// (estrategia, top_k, umbral) no aparece acá: vive en la búsqueda avanzada.
//
// La lista se acota a VISIBLE_SOURCES filas: un agente real puede tener decenas
// de fuentes (ATPCO: 69) y la lista completa enterraba Comportamiento e
// Inteligencia al fondo del panel. "Ver las N fuentes" abre el resto sin salir
// de la sección.
// =============================================================================
import { BookOpen, Check } from "@phosphor-icons/react";
import { useState } from "react";
import { AgentSourcePicker } from "./AgentSourcePicker";
import type { IngestionJob, KnowledgeSource } from "./types";
import { Button, SkeletonBlock } from "../ui";

/** Filas visibles antes de ofrecer "Ver las N fuentes". */
export const VISIBLE_SOURCES = 5;

export function AgentKnowledgeSection({
  sources,
  selectedIds,
  jobs,
  loading,
  indexingId,
  capabilitySummary,
  onToggle,
  onSetSelected,
  onIndex,
}: {
  sources: KnowledgeSource[];
  selectedIds: string[];
  jobs: IngestionJob[];
  loading: boolean;
  indexingId?: string;
  /** Qué puede consultar el agente con estas fuentes. Aparece sólo si hay. */
  capabilitySummary?: string;
  onToggle: (id: string) => void;
  onSetSelected: (ids: string[]) => void;
  onIndex: (id: string) => void;
}) {
  const [managing, setManaging] = useState(false);
  const [showAll, setShowAll] = useState(false);
  const selected = sources.filter((source) => selectedIds.includes(source.id));
  const pending = selected.filter((source) => !source.document_count).length;
  const visible = showAll ? selected : selected.slice(0, VISIBLE_SOURCES);
  const collapsible = selected.length > VISIBLE_SOURCES;

  return (
    <section className="grid gap-3" data-testid="agent-knowledge">
      <div className="flex flex-wrap items-start justify-between gap-x-3 gap-y-1">
        <div className="min-w-0">
          <h3 className="flex flex-wrap items-center gap-2 text-[13px] font-semibold tracking-[-0.01em] text-text">
            <BookOpen size={14} className="text-accent" aria-hidden />
            Conocimiento
          </h3>
          <p className="mt-0.5 text-xs leading-relaxed text-muted">
            {loading
              ? "Cargando fuentes…"
              : selectedIds.length === 0
                ? "Sin fuentes conectadas: el agente sólo responderá con su propósito."
                : `${selectedIds.length} fuente${selectedIds.length === 1 ? "" : "s"} conectada${
                    selectedIds.length === 1 ? "" : "s"
                  }`}
            {!loading && pending > 0 ? ` · ${pending} sin indexar` : ""}
          </p>
        </div>
        <Button
          variant="secondary"
          size="sm"
          aria-expanded={managing}
          aria-controls="agent-knowledge-picker"
          onClick={() => setManaging((value) => !value)}
        >
          {managing ? "Listo" : "Administrar conocimiento"}
        </Button>
      </div>

      {loading ? (
        <div data-testid="agent-knowledge-loading">
          <SkeletonBlock rows={2} />
        </div>
      ) : (
        <>
          {selected.length > 0 && (
            <ul
              id="agent-knowledge-list"
              className="grid min-w-0 gap-1"
              data-testid="agent-knowledge-list"
              aria-label="Fuentes conectadas"
            >
              {visible.map((source) => (
                <li
                  key={source.id}
                  className="grid min-w-0 grid-cols-[auto_minmax(0,1fr)_auto] items-center gap-2 text-[13px] text-text"
                >
                  <Check size={13} weight="bold" className="shrink-0 text-ok" aria-hidden />
                  <span className="min-w-0 truncate" title={source.name}>
                    {source.name}
                  </span>
                  <span className="shrink-0 text-xs text-faint tabular-nums">
                    {source.document_count ? `${source.document_count} docs` : "sin indexar"}
                  </span>
                </li>
              ))}
            </ul>
          )}

          {collapsible && (
            <div className="flex">
              <Button
                variant="ghost"
                size="sm"
                aria-expanded={showAll}
                aria-controls="agent-knowledge-list"
                onClick={() => setShowAll((value) => !value)}
              >
                {showAll ? "Ver menos" : `Ver las ${selected.length} fuentes`}
              </Button>
            </div>
          )}
        </>
      )}

      {selected.length > 0 && capabilitySummary && (
        <p className="text-xs leading-relaxed text-faint" data-testid="agent-knowledge-capabilities">
          Puede: {capabilitySummary}
        </p>
      )}

      {managing && (
        <div id="agent-knowledge-picker" className="animate-rise">
          <AgentSourcePicker
            sources={sources}
            selectedIds={selectedIds}
            jobs={jobs}
            loading={loading}
            indexingId={indexingId}
            onToggle={onToggle}
            onSetSelected={onSetSelected}
            onIndex={onIndex}
          />
        </div>
      )}
    </section>
  );
}
