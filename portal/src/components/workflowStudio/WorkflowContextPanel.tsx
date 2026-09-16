import { X } from "@phosphor-icons/react";
import type { ReactNode } from "react";
import type { DataCatalogSource } from "../../lib/dataPicker";
import type { NodeMeta } from "../../lib/workflowGraph";
import type { RunContribution } from "../WorkflowRunInspector";
import { IconButton } from "../ui";

type Props = {
  /** Fuentes del Data Catalog backend (`GET /workflows/{id}/data-catalog`). */
  sources?: DataCatalogSource[] | null;
  /** Contribuciones del último run inspeccionado. */
  contributions?: RunContribution[] | null;
  /** Catálogo backend: `contextWrites` por tipo de nodo. */
  nodes?: Record<string, NodeMeta> | null;
  onClose?: () => void;
};

function Section({ title, testId, children }: { title: string; testId: string; children: ReactNode }) {
  return (
    <section className="rounded-md border border-border bg-soft/50 p-2.5" data-testid={testId}>
      <p className="eyebrow">{title}</p>
      <div className="mt-1.5 space-y-1.5">{children}</div>
    </section>
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
    <div className="panel flex h-full flex-col overflow-hidden" data-testid="wf-context-panel">
      <header className="panel-header">
        <h3 className="text-h3">Contexto disponible</h3>
        {onClose && (
          <IconButton
            label="Cerrar contexto"
            icon={X}
            className="-mr-1 h-8 w-8"
            data-testid="wf-context-close"
            onClick={onClose}
          />
        )}
      </header>

      <div className="min-h-0 flex-1 space-y-2.5 overflow-y-auto p-3">
        <Section title="Disponibles ahora" testId="wf-context-available">
          {available.length === 0 && (
            <p className="text-[12px] leading-relaxed text-faint">
              Sin datos todavía: ejecuta el flujo o revisa el trigger.
            </p>
          )}
          {available.map((source) => (
            <p
              key={source.id}
              className="flex items-center gap-2 text-[12px] text-muted"
              data-testid={`wf-context-source-${source.id}`}
            >
              <span className="min-w-0 flex-1 truncate text-text">{source.label}</span>
              <span className="shrink-0 font-mono text-[11px] text-faint tabular-nums">
                {source.fields?.length ?? 0} datos
              </span>
            </p>
          ))}
        </Section>

        <Section title="Aportes al contexto" testId="wf-context-writes">
          {writes.length === 0 && (
            <p className="text-[12px] leading-relaxed text-faint">
              Ningún nodo aporta secciones de contexto todavía.
            </p>
          )}
          {writes.map((meta) => (
            <p
              key={meta.type}
              className="flex items-center gap-2 text-[12px]"
              data-testid={`wf-context-writes-${meta.type}`}
            >
              <span className="min-w-0 flex-1 truncate text-text">{meta.label}</span>
              <span className="shrink-0 font-mono text-[11px] text-faint">
                {(meta.contextWrites ?? []).join(", ")}
              </span>
            </p>
          ))}
        </Section>

        <Section title="Último run" testId="wf-context-run">
          {runContributions.length === 0 && (
            <p className="text-[12px] leading-relaxed text-faint">
              Sin contribuciones registradas en el último run.
            </p>
          )}
          {sections.size > 0 && (
            <div className="flex flex-wrap gap-1" data-testid="wf-context-run-sections">
              {[...sections.entries()].map(([section, count]) => (
                <span key={section} className="chip font-mono text-[10px] tabular-nums">
                  {section} · {count}
                </span>
              ))}
            </div>
          )}
          {runContributions.slice(0, 8).map((item, index) => (
            <p key={item.id ?? `${item.section}-${index}`} className="truncate text-[11px] text-faint">
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
