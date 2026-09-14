/**
 * DataView — representación humana de datos de un nodo.
 * Filas legibles primero; arrays con "Ver registros"; "Ver JSON" al final.
 */
import { CaretDown, CaretRight } from "@phosphor-icons/react";
import { useState } from "react";
import type { HumanRow } from "../../lib/humanData";
import { formatScalar, tableFromItems, toHumanRows } from "../../lib/humanData";

type Props = {
  data: unknown;
  emptyHint?: string;
  testId?: string;
};

function RowValue({ row }: { row: HumanRow }) {
  const [open, setOpen] = useState(false);
  const [showTable, setShowTable] = useState(false);
  const table = row.kind === "array" ? tableFromItems(row.value) : null;

  if (row.kind === "scalar") {
    return <span className="text-[11px] whitespace-pre-wrap text-text">{formatScalar(row.value)}</span>;
  }

  return (
    <span className="block">
      <span className="flex flex-wrap items-center gap-1.5">
        <span className="text-[11px] text-text">{row.summary}</span>
        <button
          type="button"
          className="btn btn-ghost min-h-5 px-1 text-[9px]"
          data-testid={`data-expand-${row.key}`}
          aria-expanded={open}
          onClick={() => setOpen((v) => !v)}
        >
          {open ? <CaretDown size={10} aria-hidden /> : <CaretRight size={10} aria-hidden />}
          {open ? "Ocultar" : "Ver"}
        </button>
        {table && (
          <button
            type="button"
            className="btn btn-ghost min-h-5 px-1 text-[9px]"
            data-testid={`data-registers-${row.key}`}
            onClick={() => setShowTable((v) => !v)}
          >
            {showTable ? "Ocultar registros" : "Ver registros"}
          </button>
        )}
      </span>
      {showTable && table && (
        <span className="mt-1 block overflow-x-auto rounded border border-border">
          <table className="w-full text-left text-[10px]" data-testid={`data-table-${row.key}`}>
            <thead className="bg-soft text-faint">
              <tr>
                {table.columns.map((column) => (
                  <th key={column} className="px-1.5 py-1 font-medium">{column}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {table.rows.map((cells, index) => (
                <tr key={index} className="border-t border-border/60">
                  {cells.map((cell, cellIndex) => (
                    <td key={cellIndex} className="px-1.5 py-1 text-text">{cell}</td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
          {table.total > table.rows.length && (
            <span className="block px-1.5 py-1 text-[9px] text-faint">
              Mostrando {table.rows.length} de {table.total}.
            </span>
          )}
        </span>
      )}
      {open && !showTable && <NestedView data={row.value} testId={`data-nested-${row.key}`} />}
    </span>
  );
}

function NestedView({ data, testId }: { data: unknown; testId: string }) {
  const rows = toHumanRows(data);
  if (rows.length > 0) {
    return (
      <span className="mt-1 block space-y-0.5 rounded border border-border bg-soft/40 p-1.5" data-testid={testId}>
        {rows.map((row) => (
          <span key={row.key} className="flex gap-2 text-[10px]">
            <span className="w-28 shrink-0 truncate text-faint">{row.label}</span>
            <span className="min-w-0 flex-1"><RowValue row={row} /></span>
          </span>
        ))}
      </span>
    );
  }
  const table = tableFromItems(data);
  if (table) {
    return (
      <span className="mt-1 block overflow-x-auto rounded border border-border" data-testid={testId}>
        <table className="w-full text-left text-[10px]">
          <thead className="bg-soft text-faint">
            <tr>{table.columns.map((column) => <th key={column} className="px-1.5 py-1">{column}</th>)}</tr>
          </thead>
          <tbody>
            {table.rows.map((cells, index) => (
              <tr key={index} className="border-t border-border/60">
                {cells.map((cell, cellIndex) => <td key={cellIndex} className="px-1.5 py-1 text-text">{cell}</td>)}
              </tr>
            ))}
          </tbody>
        </table>
      </span>
    );
  }
  return <span className="mt-1 block font-mono text-[10px] text-faint">{JSON.stringify(data)}</span>;
}

export function DataView({ data, emptyHint = "Sin datos registrados en este run.", testId = "wf-data-view" }: Props) {
  const [showJson, setShowJson] = useState(false);
  const rows = toHumanRows(data);
  const table = !rows.length ? tableFromItems(data) : null;

  if (!data || (rows.length === 0 && !table)) {
    return <p className="text-[11px] text-faint" data-testid={`${testId}-empty`}>{emptyHint}</p>;
  }

  return (
    <div className="space-y-2" data-testid={testId}>
      {rows.length > 0 && (
        <ul className="space-y-1">
          {rows.map((row) => (
            <li key={row.key} className="flex gap-2">
              <span className="w-28 shrink-0 truncate text-[10px] text-faint" title={row.label}>{row.label}</span>
              <span className="min-w-0 flex-1"><RowValue row={row} /></span>
            </li>
          ))}
        </ul>
      )}
      {table && (
        <div className="overflow-x-auto rounded border border-border">
          <table className="w-full text-left text-[10px]" data-testid={`${testId}-table`}>
            <thead className="bg-soft text-faint">
              <tr>{table.columns.map((column) => <th key={column} className="px-1.5 py-1">{column}</th>)}</tr>
            </thead>
            <tbody>
              {table.rows.map((cells, index) => (
                <tr key={index} className="border-t border-border/60">
                  {cells.map((cell, cellIndex) => <td key={cellIndex} className="px-1.5 py-1 text-text">{cell}</td>)}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      <button
        type="button"
        className="text-[10px] text-faint hover:text-accent"
        data-testid={`${testId}-json-toggle`}
        onClick={() => setShowJson((v) => !v)}
      >
        {showJson ? "Ocultar JSON" : "Ver JSON"}
      </button>
      {showJson && (
        <pre className="max-h-48 overflow-auto rounded bg-soft p-2 font-mono text-[9px] text-muted" data-testid={`${testId}-json`}>
          {JSON.stringify(data, null, 2)}
        </pre>
      )}
    </div>
  );
}
