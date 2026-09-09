import { BLOCK_REGISTRY, CATEGORY_LABEL, blockDef, type BlockCategory, type BlockKind } from "../lib/workflowBlocks";
import { makeBlock, reporterHints, type BlockNode } from "../lib/workflowIr";

type KB = { id: string; name: string };
type Agent = { id: string; name: string };

function walkReplace(node: BlockNode, id: string, fn: (n: BlockNode) => BlockNode | null): BlockNode | null {
  if (node.id === id) return fn(node);
  const copy: BlockNode = { ...node };
  if (node.next) {
    const n = walkReplace(node.next, id, fn);
    copy.next = n ?? undefined;
  }
  if (node.then) {
    const n = walkReplace(node.then, id, fn);
    copy.then = n ?? undefined;
  }
  if (node.else) {
    const n = walkReplace(node.else, id, fn);
    copy.else = n ?? undefined;
  }
  return copy;
}

function appendOn(node: BlockNode, id: string, slot: "next" | "then" | "else", child: BlockNode): BlockNode {
  const out = walkReplace(node, id, (n) => {
    const c: BlockNode = { ...n };
    if (slot === "then") {
      if (!c.then) c.then = child;
      else {
        const tail = { ...c.then };
        let t = tail;
        while (t.next) {
          t.next = { ...t.next };
          t = t.next;
        }
        t.next = child;
        c.then = tail;
      }
    } else if (slot === "else") {
      if (!c.else) c.else = child;
      else {
        const tail = { ...c.else };
        let t = tail;
        while (t.next) {
          t.next = { ...t.next };
          t = t.next;
        }
        t.next = child;
        c.else = tail;
      }
    } else if (!c.next) {
      c.next = child;
    } else {
      const tail = { ...c.next };
      let t = tail;
      while (t.next) {
        t.next = { ...t.next };
        t = t.next;
      }
      t.next = child;
      c.next = tail;
    }
    return c;
  });
  return out ?? node;
}

function BlockCard({
  node,
  kbs,
  agents,
  onChange,
  onRemove,
  onAdd,
}: {
  node: BlockNode;
  kbs: KB[];
  agents: Agent[];
  onChange: (n: BlockNode) => void;
  onRemove: () => void;
  onAdd: (targetId: string, slot: "next" | "then" | "else", kind: BlockKind) => void;
}) {
  const def = blockDef(node.kind);
  const hat = def.hat;
  return (
    <div className="space-y-1" data-testid={`wf-block-${node.kind}`}>
      <div className={`rounded-md border border-border p-2 ${hat ? "bg-ok-soft" : "bg-soft"}`}>
        <div className="mb-1 flex items-center gap-2">
          <span className="text-xs font-semibold text-text">{def.label}</span>
          {!hat && (
            <button type="button" className="btn btn-ghost ml-auto min-h-6 px-2 text-[10px]" onClick={onRemove}>
              Quitar
            </button>
          )}
        </div>
        <div className="grid grid-cols-1 gap-1">
          {def.fields.map((f) => {
            let options = f.options || [];
            if (f.key === "knowledge_base_id") {
              options = kbs.map((k) => ({ value: k.id, label: k.name }));
            }
            if (f.key === "agent_id") {
              options = agents.map((a) => ({ value: a.id, label: a.name }));
            }
            if (f.type === "select") {
              return (
                <label key={f.key} className="text-[10px] text-muted">
                  {f.label}
                  <select
                    className="mt-0.5 w-full rounded-md border border-border bg-surface px-2 py-1 text-xs text-text"
                    value={node.fields[f.key] || ""}
                    onChange={(e) => onChange({ ...node, fields: { ...node.fields, [f.key]: e.target.value } })}
                  >
                    <option value="">—</option>
                    {options.map((o) => (
                      <option key={o.value} value={o.value}>
                        {o.label}
                      </option>
                    ))}
                  </select>
                </label>
              );
            }
            return (
              <label key={f.key} className="text-[10px] text-muted">
                {f.label}
                <input
                  className="mt-0.5 w-full rounded-md border border-border bg-surface px-2 py-1 text-xs text-text"
                  type={f.type === "number" ? "number" : "text"}
                  placeholder={f.placeholder}
                  value={node.fields[f.key] || ""}
                  onChange={(e) => onChange({ ...node, fields: { ...node.fields, [f.key]: e.target.value } })}
                />
              </label>
            );
          })}
        </div>
        {def.hasThenElse && (
          <div className="mt-2 grid grid-cols-1 gap-2 border-l-2 border-warn pl-2 sm:grid-cols-2">
            <div>
              <p className="text-[10px] font-medium text-warn">entonces</p>
              {node.then ? (
                <BlockCard
                  node={node.then}
                  kbs={kbs}
                  agents={agents}
                  onChange={(n) => onChange({ ...node, then: n })}
                  onRemove={() => onChange({ ...node, then: node.then?.next })}
                  onAdd={onAdd}
                />
              ) : (
                <AddRow onPick={(kind) => onAdd(node.id, "then", kind)} excludeHats />
              )}
            </div>
            <div>
              <p className="text-[10px] font-medium text-muted">si no</p>
              {node.else ? (
                <BlockCard
                  node={node.else}
                  kbs={kbs}
                  agents={agents}
                  onChange={(n) => onChange({ ...node, else: n })}
                  onRemove={() => onChange({ ...node, else: node.else?.next })}
                  onAdd={onAdd}
                />
              ) : (
                <AddRow onPick={(kind) => onAdd(node.id, "else", kind)} excludeHats />
              )}
            </div>
          </div>
        )}
      </div>
      {node.next ? (
        <BlockCard
          node={node.next}
          kbs={kbs}
          agents={agents}
          onChange={(n) => onChange({ ...node, next: n })}
          onRemove={() => onChange({ ...node, next: node.next?.next })}
          onAdd={onAdd}
        />
      ) : (
        !hat && <AddRow onPick={(kind) => onAdd(node.id, "next", kind)} excludeHats />
      )}
    </div>
  );
}

function AddRow({ onPick, excludeHats }: { onPick: (kind: BlockKind) => void; excludeHats?: boolean }) {
  const items = BLOCK_REGISTRY.filter((b) => (excludeHats ? !b.hat : true));
  return (
    <select
      className="mt-1 w-full rounded-md border border-dashed border-border bg-surface px-2 py-1 text-[11px] text-muted"
      defaultValue=""
      onChange={(e) => {
        if (e.target.value) onPick(e.target.value as BlockKind);
        e.target.value = "";
      }}
    >
      <option value="">+ añadir bloque</option>
      {items.map((b) => (
        <option key={b.kind} value={b.kind}>
          {b.label}
        </option>
      ))}
    </select>
  );
}

export function WorkflowBlockEditor({
  root,
  onChange,
  kbs,
  agents,
}: {
  root: BlockNode;
  onChange: (n: BlockNode) => void;
  kbs: KB[];
  agents: Agent[];
}) {
  const hints = reporterHints(root);

  function addKind(kind: BlockKind, slot: "next" | "then" | "else" = "next", targetId?: string) {
    if (blockDef(kind).hat) {
      const hat = makeBlock(kind);
      hat.next = root.next;
      onChange(hat);
      return;
    }
    onChange(appendOn(root, targetId || root.id, slot, makeBlock(kind)));
  }

  return (
    <div className="grid grid-cols-1 gap-3 lg:grid-cols-3" data-testid="workflow-block-editor">
      <div className="space-y-2">
        <p className="text-xs font-semibold text-text">Bloques</p>
        {(Object.keys(CATEGORY_LABEL) as BlockCategory[]).map((cat) => (
          <div key={cat}>
            <p className="text-[11px] font-medium text-muted">{CATEGORY_LABEL[cat]}</p>
            <div className="mt-1 flex flex-wrap gap-1">
              {BLOCK_REGISTRY.filter((b) => b.category === cat).map((b) => (
                <button
                  key={b.kind}
                  type="button"
                  className="btn btn-ghost min-h-7 px-2 text-[10px]"
                  onClick={() => addKind(b.kind, b.hat ? "next" : "next", root.id)}
                >
                  {b.label}
                </button>
              ))}
            </div>
          </div>
        ))}
      </div>
      <div className="lg:col-span-2 space-y-2">
        <BlockCard
          node={root}
          kbs={kbs}
          agents={agents}
          onChange={onChange}
          onRemove={() => onChange(makeBlock("hat_webhook"))}
          onAdd={(id, slot, kind) => addKind(kind, slot, id)}
        />
        {!root.next && <AddRow onPick={(kind) => addKind(kind, "next", root.id)} excludeHats />}
        <div className="rounded-md border border-border bg-soft p-2" data-testid="wf-hand-panel">
          <p className="mb-1 text-xs font-semibold text-text">Datos a mano</p>
          <p className="mb-1 text-[10px] text-muted">Knowledge bases, agentes y salidas de pasos. Arrastra el nombre al prompt o condición.</p>
          <ul className="flex flex-wrap gap-1">
            {kbs.map((k) => (
              <li key={k.id} className="badge badge-muted">{k.name}</li>
            ))}
            {agents.map((a) => (
              <li key={a.id} className="badge badge-muted">{a.name}</li>
            ))}
            {hints.map((h) => (
              <li key={h}>
                <button
                  type="button"
                  className="badge badge-ok font-mono"
                  onClick={() => void navigator.clipboard.writeText(`{{${h}}}`)}
                >
                  {`{{${h}}}`}
                </button>
              </li>
            ))}
          </ul>
        </div>
      </div>
    </div>
  );
}
