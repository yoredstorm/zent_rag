/**
 * DataPicker — selector de datos de negocio.
 * Muestra "Usar dato de: <paso>" con campos legibles y su ejemplo real del
 * último run. Internamente entrega la referencia técnica, pero Simple Mode
 * nunca la muestra.
 */
import { Database, MagnifyingGlass } from "@phosphor-icons/react";
import { useMemo, useState } from "react";
import type { DataFieldOption, DataSourceOption } from "../../lib/dataPicker";

type Props = {
  sources: DataSourceOption[];
  onPick: (field: DataFieldOption, source: DataSourceOption) => void;
  label?: string;
  emptyHint?: string;
  testId?: string;
  /** Abre hacia la izquierda (rail derecho del inspector). */
  align?: "left" | "right";
};

function formatSample(value: unknown): string | null {
  if (value === undefined || value === null || value === "") return null;
  if (typeof value === "object") return null;
  const text = String(value);
  return text.length > 28 ? `${text.slice(0, 27)}…` : text;
}

export function DataPicker({
  sources,
  onPick,
  label = "dato",
  emptyHint = "Ejecuta una prueba para ver datos y campos disponibles.",
  testId = "wf-data-picker",
  align = "right",
}: Props) {
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");

  const visible = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) return sources;
    return sources
      .map((source) => ({
        ...source,
        fields: source.fields.filter(
          (f) => f.label.toLowerCase().includes(q) || f.key.toLowerCase().includes(q),
        ),
      }))
      .filter((source) => source.fields.length > 0 || source.label.toLowerCase().includes(q));
  }, [sources, query]);

  return (
    <span className="relative inline-block">
      <button
        type="button"
        className="btn btn-ghost min-h-5 gap-0.5 px-1 text-[9px]"
        data-testid={testId}
        aria-haspopup="dialog"
        aria-expanded={open}
        onClick={() => setOpen((v) => !v)}
      >
        <Database size={10} aria-hidden /> {label}
      </button>
      {open && (
        <span
          className={`absolute top-5 z-40 block w-64 overflow-hidden rounded-md border border-border bg-raised shadow-pop ${
            align === "right" ? "right-0" : "left-0"
          }`}
          role="dialog"
          aria-label="Elegir dato"
          data-testid={`${testId}-panel`}
        >
          <span className="relative block border-b border-border p-1.5">
            <MagnifyingGlass size={11} className="absolute top-1/2 left-3 -translate-y-1/2 text-faint" aria-hidden />
            <input
              className="w-full rounded border border-border bg-bg py-1 pl-6 pr-2 text-[10px]"
              placeholder="Buscar dato…"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              data-testid={`${testId}-search`}
            />
          </span>
          <span className="block max-h-64 overflow-y-auto p-1">
            {visible.length === 0 && <span className="block px-2 py-2 text-[10px] text-faint">{emptyHint}</span>}
            {visible.map((source) => (
              <span key={source.id} className="block">
                <span className="block truncate px-2 pt-1.5 pb-0.5 text-[9px] font-semibold tracking-wide text-faint uppercase">
                  {source.label}
                </span>
                {source.fields.length === 0 && (
                  <span className="block px-2 pb-1 text-[10px] text-faint">Sin campos todavía.</span>
                )}
                {source.fields.map((field) => {
                  const sample = formatSample(field.sample);
                  return (
                    <button
                      key={`${source.id}-${field.key}`}
                      type="button"
                      className="flex w-full items-center gap-2 rounded px-2 py-1 text-left hover:bg-soft"
                      data-testid={`${testId}-field-${source.id}-${field.key}`}
                      onClick={() => {
                        onPick(field, source);
                        setOpen(false);
                      }}
                    >
                      <span className="min-w-0 flex-1">
                        <span className="block truncate text-[10px] text-text">{field.label}</span>
                        {sample && <span className="block truncate text-[9px] text-faint">Ej.: {sample}</span>}
                      </span>
                      {field.type === "number" || field.type === "money" ? (
                        <span className="text-[9px] text-faint">123</span>
                      ) : null}
                    </button>
                  );
                })}
              </span>
            ))}
          </span>
        </span>
      )}
    </span>
  );
}
