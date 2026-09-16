/**
 * DataView — representación humana de datos de un nodo.
 * Filas legibles primero; arrays con "Ver registros"; "Ver JSON" al final.
 */
import { CaretDown, CaretRight } from "@phosphor-icons/react";
import { useState } from "react";
import type { HumanRow } from "../../lib/humanData";
import { formatScalar, tableFromItems, toHumanRows } from "../../lib/humanData";
import { Button } from "../ui";

type Props = {
  data: unknown;
  emptyHint?: string;
  testId?: string;
};

function DataTable({ columns, rows, testId }: { columns: string[]; rows: string[][]; testId?: string }) {
  return (
    <span className="block overflow-x-auto rounded-sm border border-border" data-testid={testId}>
      <table className="w-full border-collapse text-left text-[11px]">
        <thead className="bg-soft text-faint">
          <tr>
            {columns.map((column) => (
              <th key={column} className="border-b border-border px-2 py-1.5 font-medium">
                {column}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((cells, index) => (
            <tr key={index} className="border-t border-border-soft">
              {cells.map((cell, cellIndex) => (
                <td key={cellIndex} className="px-2 py-1.5 text-text">
                  {cell}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </span>
  );
}

function RowValue({ row }: { row: HumanRow }) {
  const [open, setOpen] = useState(false);
  const [showTable, setShowTable] = useState(false);
  const table = row.kind === "array" ? tableFromItems(row.value) : null;

  if (row.kind === "scalar") {
    return <span className="text-[12px] break-words whitespace-pre-wrap text-text">{formatScalar(row.value)}</span>;
  }

  return (
    <span className="block">
      <span className="flex flex-wrap items-center gap-1.5">
        <span className="text-[12px] text-text">{row.summary}</span>
        <Button
          variant="ghost"
          size="sm"
          className="text-[11px]"
          data-testid={`data-expand-${row.key}`}
          aria-expanded={open}
          onClick={() => setOpen((v) => !v)}
        >
          {open ? <CaretDown size={11} aria-hidden /> : <CaretRight size={11} aria-hidden />}
          {open ? "Ocultar" : "Ver"}
        </Button>
        {table && (
          <Button
            variant="ghost"
            size="sm"
            className="text-[11px]"
            data-testid={`data-registers-${row.key}`}
            onClick={() => setShowTable((v) => !v)}
          >
            {showTable ? "Ocultar registros" : "Ver registros"}
          </Button>
        )}
      </span>
      {showTable && table && (
        <span className="mt-1.5 block">
          <DataTable columns={table.columns} rows={table.rows} testId={`data-table-${row.key}`} />
          {table.total > table.rows.length && (
            <span className="mt-1 block text-[10px] text-faint">
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
      <span className="mt-1.5 block space-y-1 rounded-sm border border-border bg-soft/40 p-2" data-testid={testId}>
        {rows.map((row) => (
          <span key={row.key} className="flex gap-2 text-[11px]">
            <span className="w-28 shrink-0 truncate text-faint">{row.label}</span>
            <span className="min-w-0 flex-1">
              <RowValue row={row} />
            </span>
          </span>
        ))}
      </span>
    );
  }
  const table = tableFromItems(data);
  if (table) {
    return (
      <span className="mt-1.5 block" data-testid={testId}>
        <DataTable columns={table.columns} rows={table.rows} />
      </span>
    );
  }
  return <span className="mt-1.5 block font-mono text-[11px] break-words text-faint">{JSON.stringify(data)}</span>;
}

export function DataView({ data, emptyHint = "Sin datos registrados en este run.", testId = "wf-data-view" }: Props) {
  const [showJson, setShowJson] = useState(false);
  const rows = toHumanRows(data);
  const table = !rows.length ? tableFromItems(data) : null;

  if (!data || (rows.length === 0 && !table)) {
    return (
      <p className="text-[12px] text-faint" data-testid={`${testId}-empty`}>
        {emptyHint}
      </p>
    );
  }

  return (
    <div className="space-y-2.5" data-testid={testId}>
      {rows.length > 0 && (
        <ul className="space-y-1.5">
          {rows.map((row) => (
            <li key={row.key} className="flex gap-2">
              <span className="w-28 shrink-0 truncate text-[11px] text-faint" title={row.label}>
                {row.label}
              </span>
              <span className="min-w-0 flex-1">
                <RowValue row={row} />
              </span>
            </li>
          ))}
        </ul>
      )}
      {table && <DataTable columns={table.columns} rows={table.rows} testId={`${testId}-table`} />}
      <Button
        variant="ghost"
        size="sm"
        className="text-[11px]"
        data-testid={`${testId}-json-toggle`}
        aria-expanded={showJson}
        onClick={() => setShowJson((v) => !v)}
      >
        {showJson ? "Ocultar JSON" : "Ver JSON"}
      </Button>
      {showJson && (
        <pre
          className="max-h-48 overflow-auto rounded-sm border border-border-soft bg-control p-2 font-mono text-[11px] leading-relaxed text-muted"
          data-testid={`${testId}-json`}
        >
          {JSON.stringify(data, null, 2)}
        </pre>
      )}
    </div>
  );
}
