/**
 * DataPicker — selector de datos de negocio.
 * Muestra "Usar dato de: <paso>" con campos legibles y su ejemplo real del
 * último run. Internamente entrega la referencia técnica, pero Simple Mode
 * nunca la muestra.
 */
import { Database, MagnifyingGlass } from "@phosphor-icons/react";
import { useMemo, useState } from "react";
import type { DataFieldOption, DataSourceOption } from "../../lib/dataPicker";
import { Button, Input, Popover } from "../ui";

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
  const [query, setQuery] = useState("");
  const [open, setOpen] = useState(false);

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
    <Popover
      align={align === "right" ? "end" : "start"}
      width={288}
      className="p-0"
      open={open}
      onOpenChange={setOpen}
      trigger={
        <Button
          variant="ghost"
          size="sm"
          leadingIcon={Database}
          className="max-w-full px-1.5 text-[11px]"
          data-testid={testId}
        >
          <span className="truncate">{label}</span>
        </Button>
      }
    >
      <div className="flex flex-col" data-testid={`${testId}-panel`}>
        <div className="border-b border-border p-2">
          <Input
            icon={MagnifyingGlass}
            className="h-8 text-[12px]"
            placeholder="Buscar dato…"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            data-testid={`${testId}-search`}
            aria-label="Buscar dato"
          />
        </div>
        <div className="max-h-64 overflow-y-auto p-1">
          {visible.length === 0 && <p className="px-2 py-2 text-[12px] text-faint">{emptyHint}</p>}
          {visible.map((source) => (
            <div key={source.id} className="py-0.5">
              <p className="truncate px-2 pt-1.5 pb-0.5 text-[10px] font-semibold tracking-[0.05em] text-faint uppercase">
                {source.label}
              </p>
              {source.fields.length === 0 && (
                <p className="px-2 pb-1 text-[12px] text-faint">Sin campos todavía.</p>
              )}
              {source.fields.map((field) => {
                const sample = formatSample(field.sample);
                return (
                  <button
                    key={`${source.id}-${field.key}`}
                    type="button"
                    className="flex w-full items-center gap-2 rounded-sm px-2 py-1.5 text-left transition-colors duration-150 hover:bg-soft"
                    data-testid={`${testId}-field-${source.id}-${field.key}`}
                    onClick={() => {
                      onPick(field, source);
                      setOpen(false);
                    }}
                  >
                    <span className="min-w-0 flex-1">
                      <span className="block truncate text-[12px] text-text">{field.label}</span>
                      {sample && <span className="block truncate text-[10px] text-faint">Ej.: {sample}</span>}
                    </span>
                    {field.type === "number" || field.type === "money" ? (
                      <span className="shrink-0 font-mono text-[10px] text-faint">123</span>
                    ) : null}
                  </button>
                );
              })}
            </div>
          ))}
        </div>
      </div>
    </Popover>
  );
}
