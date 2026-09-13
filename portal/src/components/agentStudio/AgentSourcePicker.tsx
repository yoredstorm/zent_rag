import { Database, Files } from "@phosphor-icons/react";
import { Link } from "react-router-dom";
import { EmptyState, SkeletonBlock } from "../ui";
import type { KnowledgeSource } from "./types";

export function AgentSourcePicker({
  sources,
  selectedIds,
  loading,
  onToggle,
}: {
  sources: KnowledgeSource[];
  selectedIds: string[];
  loading: boolean;
  onToggle: (id: string) => void;
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
          <Link to="/knowledge/sources" className="btn btn-secondary min-h-11">
            Cargar fuentes
          </Link>
        }
      />
    );
  }

  return (
    <fieldset>
      <legend className="mb-2 text-sm font-medium text-text">Fuentes que ya cargaste</legend>
      <p className="mb-3 text-xs text-muted">Elige con qué material responde este agente.</p>
      <div className="grid gap-2">
        {sources.map((source) => {
          const checked = selectedIds.includes(source.id);
          const empty = !source.document_count;
          return (
            <label
              key={source.id}
              className={`flex min-h-11 cursor-pointer items-start gap-3 rounded-md border px-3 py-2.5 ${
                checked ? "border-accent bg-accent-soft/40" : "border-border"
              }`}
            >
              <input
                type="checkbox"
                className="mt-1"
                checked={checked}
                onChange={() => onToggle(source.id)}
              />
              <span className="min-w-0 flex-1">
                <span className="flex items-center gap-2 text-sm font-medium text-text">
                  <Files size={14} className="text-accent" aria-hidden />
                  {source.name}
                </span>
                <span className="mt-0.5 block text-xs text-faint">
                  {source.type} · {source.status} · {source.document_count} docs
                </span>
                {empty && (
                  <span className="mt-1 block text-xs text-warn">Aún no indexada</span>
                )}
              </span>
            </label>
          );
        })}
      </div>
    </fieldset>
  );
}
