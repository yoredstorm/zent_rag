import { Database, Files, MagnifyingGlass } from "@phosphor-icons/react";
import { useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { Button, Checkbox, EmptyState, Input, SkeletonBlock, cn } from "../ui";
import type { IngestionJob, KnowledgeSource } from "./types";

export const INDEXING_COPY =
  "Zent está leyendo el PDF, troceándolo y pasándolo a vectores. Hasta que haya documentos, el agente no puede citarlo.";

export const MAX_AGENT_SOURCES = 500;
export const AGENT_SOURCE_CAP_MSG = "Un agente admite como máximo 500 fuentes.";

const ACTIVE_JOB = new Set(["pending", "running"]);

export function latestJobForSource(sourceId: string, jobs: IngestionJob[]): IngestionJob | undefined {
  return jobs.find((job) => job.source_id === sourceId);
}

function humanStatus(source: KnowledgeSource, job: IngestionJob | undefined): string {
  if (source.document_count > 0) return `${source.document_count} docs`;
  if (job?.status === "pending") return "En cola";
  if (job?.status === "running") return "Indexando";
  if (job?.status === "failed" || job?.status === "dead") return "Falló el indexado";
  return "Sin indexar";
}

/** Estado real de la fuente: alimenta el activity rail de cada fila. */
function railState(
  source: KnowledgeSource,
  job: IngestionJob | undefined,
): "ready" | "queued" | "running" | "warning" | "failed" {
  if (job?.status === "failed" || job?.status === "dead") return "failed";
  if (job?.status === "running") return "running";
  if (job?.status === "pending") return "queued";
  if (source.document_count > 0) return "ready";
  return "warning";
}

export function AgentSourcePicker({
  sources,
  selectedIds,
  jobs,
  loading,
  indexingId,
  onToggle,
  onIndex,
  onSetSelected,
}: {
  sources: KnowledgeSource[];
  selectedIds: string[];
  jobs: IngestionJob[];
  loading: boolean;
  indexingId?: string;
  onToggle: (id: string) => void;
  onIndex: (id: string) => void;
  onSetSelected?: (ids: string[]) => void;
}) {
  const [query, setQuery] = useState("");
  const [capError, setCapError] = useState("");

  const visible = useMemo(() => {
    const term = query.trim().toLowerCase();
    if (!term) return sources;
    return sources.filter(
      (source) =>
        source.name.toLowerCase().includes(term) || source.type.toLowerCase().includes(term),
    );
  }, [query, sources]);

  function tryToggle(id: string) {
    const checked = selectedIds.includes(id);
    if (!checked && selectedIds.length >= MAX_AGENT_SOURCES) {
      setCapError(AGENT_SOURCE_CAP_MSG);
      return;
    }
    setCapError("");
    onToggle(id);
  }

  function selectVisible() {
    const next = [...selectedIds];
    const seen = new Set(next);
    let truncated = false;
    for (const source of visible) {
      if (seen.has(source.id)) continue;
      if (next.length >= MAX_AGENT_SOURCES) {
        truncated = true;
        break;
      }
      next.push(source.id);
      seen.add(source.id);
    }
    setCapError(truncated ? AGENT_SOURCE_CAP_MSG : "");
    if (onSetSelected) {
      onSetSelected(next);
      return;
    }
    for (const id of next) {
      if (!selectedIds.includes(id)) onToggle(id);
    }
  }

  function clearSelected() {
    setCapError("");
    if (onSetSelected) {
      onSetSelected([]);
      return;
    }
    for (const id of selectedIds) onToggle(id);
  }

  if (loading) {
    return (
      <div className="panel p-4">
        <SkeletonBlock rows={3} />
      </div>
    );
  }

  if (sources.length === 0) {
    return (
      <EmptyState
        icon={Database}
        title="Sin fuentes cargadas"
        body="Carga documentos o conectores en Fuentes y vuelve para asignarlos a este agente."
        action={
          <Link to="/knowledge/sources" className="btn btn-secondary">
            Cargar fuentes
          </Link>
        }
      />
    );
  }

  const waiting = sources.some((source) => selectedIds.includes(source.id) && !source.document_count);

  return (
    <fieldset className="min-w-0">
      <legend className="text-h3">Fuentes que ya cargaste</legend>
      <p className="mt-0.5 text-xs leading-relaxed text-muted">
        Elige con qué material responde este agente.
      </p>
      <div className="mt-3 flex flex-wrap items-center gap-2">
        <Input
          type="search"
          icon={MagnifyingGlass}
          aria-label="Buscar fuentes"
          placeholder="Buscar por nombre"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          className="w-full sm:w-56"
        />
        <span className="text-xs text-faint tabular-nums">
          {selectedIds.length} seleccionadas / {sources.length}
        </span>
        <Button variant="ghost" size="sm" onClick={selectVisible} disabled={visible.length === 0}>
          Marcar visibles
        </Button>
        <Button variant="ghost" size="sm" onClick={clearSelected} disabled={selectedIds.length === 0}>
          Quitar selección
        </Button>
      </div>
      {capError ? (
        <p className="mt-2 text-xs text-danger" role="alert">
          {capError}
        </p>
      ) : null}
      {waiting && (
        <p
          className="mt-3 rounded-md border border-warn/25 bg-warn-soft px-3 py-2.5 text-xs leading-relaxed text-warn"
          data-testid="source-indexing-copy"
          role="status"
        >
          {INDEXING_COPY}
        </p>
      )}
      <div
        data-testid="source-picker-list"
        className="mt-3 max-h-72 space-y-1 overflow-y-auto pr-1"
      >
        {visible.length === 0 ? (
          <p className="px-1 py-2 text-xs text-muted">Ninguna fuente coincide con la búsqueda.</p>
        ) : (
          visible.map((source) => {
            const checked = selectedIds.includes(source.id);
            const job = latestJobForSource(source.id, jobs);
            const empty = !source.document_count;
            const active = Boolean(job && ACTIVE_JOB.has(job.status));
            const progress = Math.max(0, Math.min(100, job?.progress ?? 0));
            return (
              <div
                key={source.id}
                data-state={railState(source, job)}
                className={cn(
                  "state-rail flex items-center gap-2 rounded-md border py-1.5 pr-2 pl-3",
                  checked ? "border-accent-line bg-accent-soft/40" : "border-border",
                )}
              >
                <Checkbox
                  className="min-w-0 flex-1 items-center"
                  id={`agent-source-${source.id}`}
                  checked={checked}
                  onCheckedChange={() => tryToggle(source.id)}
                  label={
                    <span className="block min-w-0">
                      <span className="flex min-w-0 items-center gap-2">
                        <Files size={14} className="shrink-0 text-accent" aria-hidden />
                        <span className="truncate font-medium text-text">{source.name}</span>
                        <span className="shrink-0 text-xs text-faint">
                          {source.type} · {humanStatus(source, job)}
                        </span>
                      </span>
                      {empty && active && (
                        <span className="progress-track mt-1.5 block" data-testid={`source-progress-${source.id}`}>
                          {progress > 0 ? (
                            <span className="progress-fill block" style={{ width: `${progress}%` }} />
                          ) : (
                            <span className="progress-fill block w-1/3 animate-pulse" />
                          )}
                        </span>
                      )}
                      {empty && !active && (
                        <span className="mt-0.5 block text-xs text-warn">Aún no indexada</span>
                      )}
                    </span>
                  }
                />
                {empty && !active && (
                  <Button
                    size="sm"
                    className="shrink-0"
                    loading={indexingId === source.id}
                    data-testid={`source-index-${source.id}`}
                    onClick={() => onIndex(source.id)}
                  >
                    Indexar ahora
                  </Button>
                )}
              </div>
            );
          })
        )}
      </div>
    </fieldset>
  );
}
