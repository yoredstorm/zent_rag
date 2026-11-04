import { useEffect, useRef, type ReactNode } from "react";

export type ContextMenuItem =
  | { kind: "item"; id: string; label: string; hint?: string; icon?: ReactNode; danger?: boolean; disabled?: boolean; onSelect: () => void }
  | { kind: "separator"; id: string };

type Props = {
  x: number;
  y: number;
  items: ContextMenuItem[];
  onClose: () => void;
  /** Límites del contenedor para que el menú no salga del lienzo. */
  bounds: { w: number; h: number };
};

/** Menú contextual del lienzo: flechas para moverse, Enter para elegir, Esc para cerrar. */
export function CanvasContextMenu({ x, y, items, onClose, bounds }: Props) {
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    ref.current?.querySelector<HTMLButtonElement>("button:not([disabled])")?.focus();
    function onDown(ev: globalThis.PointerEvent) {
      if (!ref.current?.contains(ev.target as Node)) onClose();
    }
    window.addEventListener("pointerdown", onDown, true);
    return () => window.removeEventListener("pointerdown", onDown, true);
  }, [onClose]);

  const width = 232;
  const height = items.length * 34;
  const left = Math.max(8, Math.min(x, bounds.w - width - 8));
  const top = Math.max(8, Math.min(y, bounds.h - height - 8));

  return (
    <div
      ref={ref}
      role="menu"
      aria-label="Acciones del lienzo"
      data-testid="wf-canvas-menu"
      className="absolute z-40 animate-pop-in rounded-lg border border-border bg-overlay p-1 shadow-pop"
      style={{ left, top, width }}
      onPointerDown={(ev) => ev.stopPropagation()}
      onContextMenu={(ev) => ev.preventDefault()}
      onKeyDown={(ev) => {
        const buttons = [...(ref.current?.querySelectorAll<HTMLButtonElement>("button:not([disabled])") ?? [])];
        const index = buttons.indexOf(document.activeElement as HTMLButtonElement);
        if (ev.key === "ArrowDown") {
          ev.preventDefault();
          buttons[(index + 1) % buttons.length]?.focus();
        } else if (ev.key === "ArrowUp") {
          ev.preventDefault();
          buttons[(index - 1 + buttons.length) % buttons.length]?.focus();
        } else if (ev.key === "Escape") {
          ev.preventDefault();
          ev.stopPropagation();
          onClose();
        }
      }}
    >
      {items.map((item) =>
        item.kind === "separator" ? (
          <div key={item.id} role="separator" className="my-1 h-px bg-border" />
        ) : (
          <button
            key={item.id}
            type="button"
            role="menuitem"
            disabled={item.disabled}
            data-testid={`wf-menu-${item.id}`}
            className={`flex min-h-8 w-full cursor-pointer items-center gap-2.5 rounded-sm px-2.5 text-left text-[13px] outline-none focus-visible:bg-soft disabled:cursor-not-allowed disabled:opacity-45 ${
              item.danger ? "text-danger hover:bg-danger-soft" : "text-text hover:bg-soft"
            }`}
            onClick={() => {
              onClose();
              item.onSelect();
            }}
          >
            {item.icon && <span className="flex w-4 shrink-0 justify-center text-muted">{item.icon}</span>}
            <span className="min-w-0 flex-1 truncate">{item.label}</span>
            {item.hint && <kbd className="text-[11px] text-faint">{item.hint}</kbd>}
          </button>
        ),
      )}
    </div>
  );
}
