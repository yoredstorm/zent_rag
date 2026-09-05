import { Moon, Sun, Monitor, CaretDown } from "@phosphor-icons/react";
import { useEffect, useRef, useState } from "react";
import { useTheme, type ThemePreference } from "../lib/theme";

const OPTIONS: { id: ThemePreference; label: string; icon: typeof Sun }[] = [
  { id: "system", label: "System", icon: Monitor },
  { id: "light", label: "Light", icon: Sun },
  { id: "dark", label: "Dark", icon: Moon },
];

export function ThemeToggle({ compact = false }: { compact?: boolean }) {
  const { preference, setPreference } = useTheme();
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    function onPointer(event: PointerEvent) {
      if (!ref.current?.contains(event.target as Node)) setOpen(false);
    }
    function onKey(event: KeyboardEvent) {
      if (event.key === "Escape") setOpen(false);
    }
    document.addEventListener("pointerdown", onPointer);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("pointerdown", onPointer);
      document.removeEventListener("keydown", onKey);
    };
  }, [open]);

  const current = OPTIONS.find((o) => o.id === preference) ?? OPTIONS[0];

  return (
    <div className="relative" ref={ref}>
      <button
        type="button"
        className="inline-flex h-9 items-center gap-1.5 rounded-sm px-2 text-muted transition-colors duration-150 hover:bg-soft hover:text-text"
        aria-haspopup="menu"
        aria-expanded={open}
        aria-label={`Tema: ${current.label}`}
        onClick={() => setOpen((v) => !v)}
      >
        <current.icon size={15} aria-hidden />
        {!compact && <span className="text-xs">{current.label}</span>}
        <CaretDown size={11} className="text-faint" aria-hidden />
      </button>
      {open && (
        <div
          role="menu"
          aria-label="Tema de color"
          className="absolute right-0 top-full z-40 mt-1.5 w-40 overflow-hidden rounded-md border border-border bg-raised shadow-pop"
        >
          {OPTIONS.map((opt) => (
            <button
              key={opt.id}
              type="button"
              role="menuitemradio"
              aria-checked={opt.id === preference}
              className={`flex w-full items-center gap-2 px-3 py-2 text-left text-[13px] transition-colors duration-150 ${
                opt.id === preference ? "bg-accent-soft font-medium text-accent" : "text-muted hover:bg-soft hover:text-text"
              }`}
              onClick={() => {
                setPreference(opt.id);
                setOpen(false);
              }}
            >
              <opt.icon size={15} aria-hidden />
              {opt.label}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}