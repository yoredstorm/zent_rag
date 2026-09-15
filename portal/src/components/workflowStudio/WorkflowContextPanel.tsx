import { X } from "@phosphor-icons/react";
import type { DataCatalogSource } from "../../lib/dataPicker";
import type { NodeMeta } from "../../lib/workflowGraph";
import type { RunContribution } from "../WorkflowRunInspector";

type Props = {
  /** Fuentes del Data Catalog backend (`GET /workflows/{id}/data-catalog`). */
  sources?: DataCatalogSource[] | null;
  /** Contribuciones del último run inspeccionado. */
  contributions?: RunContribution[] | null;
  /** Catálogo backend: `contextWrites` por tipo de nodo. */
  nodes?: Record<string, NodeMeta> | null;
  onClose?: () => void;
};

function Section({ title, testId, children }: { title: string; testId: string; children: React.ReactNode }) {
  return (
    <div className="rounded-md border border-border bg-soft/60 px-2 py-1.5" data-testid={testId}>
      <p className="text-[10px] font-semibold tracking-wide text-muted uppercase">{title}</p>
      <div className="mt-1 space-y-1">{children}</div>
    </div>
  );
}

/**
 * Panel de contexto del editor (Fase 7): qué datos están disponibles, qué
 * aporta cada nodo al contexto compartido y qué se registró en el último run.
 * Solo lectura; combina data-catalog + catálogo de nodos + inspector.
 */
export function WorkflowContextPanel({ sources, contributions, nodes, onClose }: Props) {
  const available = sources ?? [];
  const runContributions = contributions ?? [];
  const writes = Object.values(nodes ?? {}).filter((meta) => (meta.contextWrites ?? []).length > 0);
  const sections = new Map<string, number>();
  for (const item of runContributions) {
    sections.set(item.section, (sections.get(item.section) ?? 0) + 1);
  }

  return (
    <div
      className="flex h-full flex-col overflow-hidden rounded-lg border border-border bg-surface shadow-panel"
      data-testid="wf-context-panel"
    >
      <div className="flex items-center gap-2 border-b border-border px-2.5 py-2">
        <h3 className="min-w-0 flex-1 truncate text-[12px] font-semibold text-text">Contexto disponible</h3>
        {onClose && (
          <button
            type="button"
            className="btn btn-ghost min-h-7 px-1.5"
            aria-label="Cerrar contexto"
            data-testid="wf-context-close"
            onClick={onClose}
          >
            <X size={13} aria-hidden />
          </button>
        )}
      </div>

      <div className="space-y-2 overflow-y-auto p-2">
        <Section title="Disponibles ahora" testId="wf-context-available">
          {available.length === 0 && (
            <p className="text-[10px] text-faint">Sin datos todavía: ejecuta el flujo o revisa el trigger.</p>
          )}
          {available.map((source) => (
            <p key={source.id} className="flex items-center gap-2 text-[10px] text-muted" data-testid={`wf-context-source-${source.id}`}>
              <span className="min-w-0 flex-1 truncate text-text">{source.label}</span>
              <span className="shrink-0 text-faint">{source.fields?.length ?? 0} datos</span>
            </p>
          ))}
        </Section>

        <Section title="Aportes al contexto" testId="wf-context-writes">
          {writes.length === 0 && (
            <p className="text-[10px] text-faint">Ningún nodo aporta secciones de contexto todavía.</p>
          )}
          {writes.map((meta) => (
            <p key={meta.type} className="flex items-center gap-2 text-[10px]" data-testid={`wf-context-writes-${meta.type}`}>
              <span className="min-w-0 flex-1 truncate text-text">{meta.label}</span>
              <span className="shrink-0 text-faint">{(meta.contextWrites ?? []).join(", ")}</span>
            </p>
          ))}
        </Section>

        <Section title="Último run" testId="wf-context-run">
          {runContributions.length === 0 && (
            <p className="text-[10px] text-faint">Sin contribuciones registradas en el último run.</p>
          )}
          {sections.size > 0 && (
            <p className="flex flex-wrap gap-1" data-testid="wf-context-run-sections">
              {[...sections.entries()].map(([section, count]) => (
                <span key={section} className="rounded border border-border bg-bg px-1.5 py-0.5 text-[9px] text-muted">
                  {section} · {count}
                </span>
              ))}
            </p>
          )}
          {runContributions.slice(0, 8).map((item, index) => (
            <p key={item.id ?? `${item.section}-${index}`} className="truncate text-[10px] text-faint">
              <span className="text-text">{item.section}</span>
              {item.node_id ? ` · ${item.node_id}` : ""}
              {item.payload?.label ? ` · ${String(item.payload.label)}` : ""}
            </p>
          ))}
        </Section>
      </div>
    </div>
  );
}
