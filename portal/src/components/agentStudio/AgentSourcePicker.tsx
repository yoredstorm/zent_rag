import { Database, Files } from "@phosphor-icons/react";
import { Link } from "react-router-dom";
import { Button, Checkbox, EmptyState, SkeletonBlock, cn } from "../ui";
import type { IngestionJob, KnowledgeSource } from "./types";

export const INDEXING_COPY =
  "Zent está leyendo el PDF, troceándolo y pasándolo a vectores. Hasta que haya documentos, el agente no puede citarlo.";

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
}: {
  sources: KnowledgeSource[];
  selectedIds: string[];
  jobs: IngestionJob[];
  loading: boolean;
  indexingId?: string;
  onToggle: (id: string) => void;
  onIndex: (id: string) => void;
}) {
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
      {waiting && (
        <p
          className="mt-3 rounded-md border border-warn/25 bg-warn-soft px-3 py-2.5 text-xs leading-relaxed text-warn"
          data-testid="source-indexing-copy"
          role="status"
        >
          {INDEXING_COPY}
        </p>
      )}
      <div className="mt-3 grid gap-2">
        {sources.map((source) => {
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
                "state-rail flex items-start gap-2 rounded-md border py-2.5 pr-3 pl-4",
                checked ? "border-accent-line bg-accent-soft/40" : "border-border",
              )}
            >
              <Checkbox
                className="min-w-0 flex-1"
                id={`agent-source-${source.id}`}
                checked={checked}
                onCheckedChange={() => onToggle(source.id)}
                label={
                  <span className="block min-w-0">
                    <span className="flex items-center gap-2 font-medium text-text">
                      <Files size={14} className="shrink-0 text-accent" aria-hidden />
                      <span className="truncate">{source.name}</span>
                    </span>
                    <span className="mt-0.5 block text-xs text-faint">
                      {source.type} · {humanStatus(source, job)}
                    </span>
                    {empty && active && (
                      <span className="progress-track mt-2 block" data-testid={`source-progress-${source.id}`}>
                        {progress > 0 ? (
                          <span className="progress-fill block" style={{ width: `${progress}%` }} />
                        ) : (
                          <span className="progress-fill block w-1/3 animate-pulse" />
                        )}
                      </span>
                    )}
                    {empty && !active && (
                      <span className="mt-1 block text-xs text-warn">Aún no indexada</span>
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
        })}
      </div>
    </fieldset>
  );
}
