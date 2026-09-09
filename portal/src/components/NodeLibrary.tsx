import { MagnifyingGlass } from "@phosphor-icons/react";
import { useMemo, useState } from "react";
import { CATEGORY_META, NODE_LIBRARY, type NodeCategory, type NodeMeta } from "../lib/workflowGraph";

type Props = {
  onAdd: (meta: NodeMeta) => void;
  usedTypes: string[];
};

const ORDER: NodeCategory[] = ["trigger", "data", "ai", "integration", "logic", "control", "output"];

export function NodeLibrary({ onAdd, usedTypes }: Props) {
  const [q, setQ] = useState("");
  const items = useMemo(() => Object.values(NODE_LIBRARY).filter((m) => !m.type.startsWith("trigger_") || usedTypes.length === 0), [usedTypes]);
  const filtered = items.filter(
    (m) => !q || m.label.toLowerCase().includes(q.toLowerCase()) || m.type.includes(q.toLowerCase())
  );

  return (
    <aside className="flex h-[560px] w-56 shrink-0 flex-col overflow-hidden rounded-md border border-border bg-raised/60" data-testid="wf-node-library">
      <div className="border-b border-border p-2">
        <h3 className="text-[11px] font-semibold tracking-wide text-faint uppercase">Nodos</h3>
        <div className="relative mt-1.5">
          <MagnifyingGlass size={12} className="absolute top-1/2 left-2 -translate-y-1/2 text-faint" aria-hidden />
          <input
            className="w-full rounded-md border border-border bg-bg py-1 pl-6 pr-2 text-[11px]"
            placeholder="Buscar nodo…"
            value={q}
            onChange={(e) => setQ(e.target.value)}
          />
        </div>
      </div>
      <div className="flex-1 space-y-2 overflow-y-auto p-2">
        {ORDER.map((cat) => {
          const group = filtered.filter((m) => m.category === cat);
          if (group.length === 0) return null;
          return (
            <div key={cat}>
              <p className={`px-1 text-[9px] font-semibold tracking-wider uppercase ${CATEGORY_META[cat].color}`}>
                {CATEGORY_META[cat].label}
              </p>
              <div className="mt-1 space-y-1">
                {group.map((m) => (
                  <button
                    key={m.type}
                    type="button"
                    data-testid={`wf-add-${m.type}`}
                    className="flex w-full items-center gap-2 rounded-md border border-border bg-soft/60 px-2 py-1.5 text-left transition-colors hover:border-accent/40 hover:bg-soft"
                    onClick={() => onAdd(m)}
                  >
                    <span className="flex h-6 w-6 items-center justify-center rounded bg-bg text-[12px]" aria-hidden>
                      {m.icon}
                    </span>
                    <span className="min-w-0">
                      <span className="block truncate text-[11px] font-medium text-text">{m.label}</span>
                      <span className="block truncate text-[9px] text-faint">{m.risk && m.risk !== "normal" ? `riesgo ${m.risk}` : "—"}</span>
                    </span>
                  </button>
                ))}
              </div>
            </div>
          );
        })}
        {filtered.length === 0 && <p className="px-1 text-[10px] text-faint">Sin nodos para “{q}”</p>}
      </div>
    </aside>
  );
}