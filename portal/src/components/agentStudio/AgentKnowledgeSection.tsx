// =============================================================================
// AgentKnowledgeSection — CONOCIMIENTO de alto nivel.
// =============================================================================
// El usuario elige QUÉ información puede usar el agente. CÓMO consultarla
// (estrategia, top_k, umbral) no aparece acá: vive en la búsqueda avanzada.
// =============================================================================
import { BookOpen, Check } from "@phosphor-icons/react";
import { useState } from "react";
import { AgentSourcePicker } from "./AgentSourcePicker";
import type { IngestionJob, KnowledgeSource } from "./types";
import { Button } from "../ui";

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
  const selected = sources.filter((source) => selectedIds.includes(source.id));
  const pending = selected.filter((source) => !source.document_count).length;

  return (
    <section className="grid gap-3" data-testid="agent-knowledge">
      <div className="flex flex-wrap items-start justify-between gap-x-3 gap-y-1">
        <div className="min-w-0">
          <h3 className="flex flex-wrap items-center gap-2 text-[13px] font-semibold tracking-[-0.01em] text-text">
            <BookOpen size={14} className="text-accent" aria-hidden />
            Conocimiento
          </h3>
          <p className="mt-0.5 text-xs leading-relaxed text-muted">
            {selectedIds.length === 0
              ? "Sin fuentes conectadas: el agente sólo responderá con su propósito."
              : `${selectedIds.length} fuente${selectedIds.length === 1 ? "" : "s"} conectada${
                  selectedIds.length === 1 ? "" : "s"
                }`}
            {pending > 0 ? ` · ${pending} sin indexar` : ""}
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

      {selected.length > 0 && (
        <ul className="grid gap-1" data-testid="agent-knowledge-list">
          {selected.map((source) => (
            <li key={source.id} className="flex items-center gap-2 text-[13px] text-text">
              <Check size={13} weight="bold" className="shrink-0 text-ok" aria-hidden />
              <span className="min-w-0 truncate">{source.name}</span>
              <span className="ml-auto shrink-0 text-xs text-faint tabular-nums">
                {source.document_count ? `${source.document_count} docs` : "sin indexar"}
              </span>
            </li>
          ))}
        </ul>
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
