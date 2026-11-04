import { MagnifyingGlass, X } from "@phosphor-icons/react";
import { useEffect, useMemo, useRef, useState } from "react";
import { canvasNodeKind, canvasNodeKindMeta } from "../../lib/canvasNodeKind";
import { searchGraphNodes } from "../../lib/graphSearch";
import type { WorkflowGraph } from "../../lib/workflowGraph";

type Props = {
  graph: WorkflowGraph;
  onPick: (nodeId: string) => void;
  onClose: () => void;
};

/** Buscador de nodos del lienzo (Ctrl+F): nombre, tipo o id; Enter centra y selecciona. */
export function CanvasSearch({ graph, onPick, onClose }: Props) {
  const [q, setQ] = useState("");
  const [active, setActive] = useState(0);
  const inputRef = useRef<HTMLInputElement>(null);
  const hits = useMemo(() => searchGraphNodes(graph.nodes, q, 12), [graph.nodes, q]);

  useEffect(() => {
    inputRef.current?.focus();
  }, []);

  useEffect(() => {
    setActive(0);
  }, [q]);

  return (
    <div
      className="w-[min(420px,calc(100%-2rem))] overflow-hidden rounded-lg border border-border bg-overlay shadow-pop"
      data-testid="wf-canvas-search"
      role="dialog"
      aria-label="Buscar nodo en el lienzo"
      onPointerDown={(ev) => ev.stopPropagation()}
    >
      <div className="flex items-center gap-2 border-b border-border px-3">
        <MagnifyingGlass size={15} className="shrink-0 text-faint" aria-hidden />
        <input
          ref={inputRef}
          value={q}
          onChange={(ev) => setQ(ev.target.value)}
          placeholder="Buscar por nombre, tipo o id…"
          aria-label="Buscar nodo en el lienzo"
          aria-controls="wf-canvas-search-results"
          aria-activedescendant={hits[active] ? `wf-search-hit-${hits[active].node.id}` : undefined}
          data-testid="wf-canvas-search-input"
          className="h-11 min-w-0 flex-1 bg-transparent text-[13px] text-text outline-none placeholder:text-faint"
          onKeyDown={(ev) => {
            if (ev.key === "ArrowDown") {
              ev.preventDefault();
              setActive((i) => Math.min(hits.length - 1, i + 1));
            } else if (ev.key === "ArrowUp") {
              ev.preventDefault();
              setActive((i) => Math.max(0, i - 1));
            } else if (ev.key === "Enter" && hits[active]) {
              ev.preventDefault();
              onPick(hits[active].node.id);
            } else if (ev.key === "Escape") {
              ev.preventDefault();
              ev.stopPropagation();
              onClose();
            }
          }}
        />
        <span className="hidden text-[11px] text-faint sm:inline">{hits.length} nodos</span>
        <button
          type="button"
          className="flex h-8 w-8 cursor-pointer items-center justify-center rounded-sm text-faint hover:bg-soft hover:text-text"
          aria-label="Cerrar búsqueda"
          onClick={onClose}
        >
          <X size={14} aria-hidden />
        </button>
      </div>
      <ul id="wf-canvas-search-results" role="listbox" className="max-h-72 overflow-y-auto p-1">
        {hits.map((hit, i) => {
          const meta = canvasNodeKindMeta(canvasNodeKind(hit.node, graph.metadata));
          const Icon = meta.icon;
          return (
            <li
              key={hit.node.id}
              id={`wf-search-hit-${hit.node.id}`}
              role="option"
              aria-selected={i === active}
              data-testid="wf-canvas-search-hit"
              className={`flex cursor-pointer items-center gap-2.5 rounded-sm px-2.5 py-2 ${i === active ? "bg-soft" : "hover:bg-soft/70"}`}
              onMouseEnter={() => setActive(i)}
              onClick={() => onPick(hit.node.id)}
            >
              <Icon size={15} className={`shrink-0 ${meta.text}`} aria-hidden />
              <span className="min-w-0 flex-1">
                <span className="block truncate text-[13px] text-text">{hit.label}</span>
                <span className="block truncate text-[11px] text-faint">
                  {hit.typeLabel} · <span className="font-mono">{hit.node.id}</span>
                </span>
              </span>
            </li>
          );
        })}
        {hits.length === 0 && <li className="px-2.5 py-3 text-[12px] text-faint">Sin nodos para “{q}”.</li>}
      </ul>
    </div>
  );
}
