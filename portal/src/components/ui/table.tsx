import { CaretDown, CaretUp, CaretLeft, CaretRight } from "@phosphor-icons/react";
import type { HTMLAttributes, ReactNode } from "react";
import { cn } from "./cn";
import { ErrorInline, SkeletonTable } from "./states";
import { IconButton } from "./Button";

export type SortDir = "asc" | "desc";
export type SortState = { key: string; dir: SortDir } | null;

export type Column<T> = {
  key: string;
  header: ReactNode;
  render: (row: T) => ReactNode;
  align?: "left" | "center" | "right";
  width?: string;
  sortable?: boolean;
  /** Oculta la columna por debajo del breakpoint indicado. */
  hideBelow?: "md" | "lg" | "xl";
  className?: string;
};

const ALIGN: Record<NonNullable<Column<unknown>["align"]>, string> = {
  left: "text-left",
  center: "text-center",
  right: "text-right",
};

const HIDE: Record<NonNullable<Column<unknown>["hideBelow"]>, string> = {
  md: "hidden md:table-cell",
  lg: "hidden lg:table-cell",
  xl: "hidden xl:table-cell",
};

export type DataTableProps<T> = {
  columns: Column<T>[];
  rows: T[];
  rowKey: (row: T) => string;
  caption?: string;
  loading?: boolean;
  error?: string | null;
  /** Estado vacío: explicar qué falta y qué hacer. */
  empty?: ReactNode;
  dense?: boolean;
  stickyHeader?: boolean;
  onRowClick?: (row: T) => void;
  isRowSelected?: (row: T) => boolean;
  /** Props extra por fila (por ejemplo `data-testid`). */
  rowProps?: (row: T) => HTMLAttributes<HTMLTableRowElement>;
  rowActions?: (row: T) => ReactNode;
  sort?: SortState;
  onSortChange?: (sort: SortState) => void;
  /** Controles de filtro/fecha sobre la tabla. */
  toolbar?: ReactNode;
  footer?: ReactNode;
  className?: string;
};

/**
 * Tabla de datos del sistema: sorting controlado, estados de carga/vacío/error,
 * sticky header, selección de fila y acciones. No encapsula la tabla en cards.
 */
export function DataTable<T>({
  columns,
  rows,
  rowKey,
  caption,
  loading = false,
  error = null,
  empty,
  dense = false,
  stickyHeader = false,
  onRowClick,
  isRowSelected,
  rowProps,
  rowActions,
  sort,
  onSortChange,
  toolbar,
  footer,
  className,
}: DataTableProps<T>) {
  function toggleSort(key: string) {
    if (!onSortChange) return;
    if (sort?.key !== key) {
      onSortChange({ key, dir: "asc" });
      return;
    }
    onSortChange(sort.dir === "asc" ? { key, dir: "desc" } : null);
  }

  const cellPad = dense ? "px-3 py-2" : "px-3 py-2.5";
  // Defensivo: una respuesta inesperada (payload de error, objeto en vez de
  // lista) no debe tumbar la página entera vía ErrorBoundary.
  const safeRows = Array.isArray(rows) ? rows : [];

  return (
    <div className={cn("min-w-0", className)}>
      {toolbar && <div className="mb-3 flex flex-wrap items-center gap-2">{toolbar}</div>}
      {error ? (
        <ErrorInline message={error} />
      ) : loading ? (
        <div className="panel overflow-hidden">
          <SkeletonTable rows={6} cols={Math.min(Array.isArray(columns) ? columns.length : 1, 5)} />
        </div>
      ) : safeRows.length === 0 ? (
        <div className="panel">{empty}</div>
      ) : (
        <div className="panel overflow-x-auto">
          <table className={cn("table", stickyHeader && "table-sticky")}>
            {caption && <caption className="sr-only">{caption}</caption>}
            <thead>
              <tr>
                {columns.map((col) => {
                  const active = sort?.key === col.key;
                  return (
                    <th
                      key={col.key}
                      scope="col"
                      style={col.width ? { width: col.width } : undefined}
                      className={cn(
                        ALIGN[col.align ?? "left"],
                        col.hideBelow && HIDE[col.hideBelow],
                        col.className
                      )}
                      aria-sort={
                        active ? (sort?.dir === "asc" ? "ascending" : "descending") : undefined
                      }
                    >
                      {col.sortable && onSortChange ? (
                        <button
                          type="button"
                          onClick={() => toggleSort(col.key)}
                          className={cn(
                            "inline-flex cursor-pointer items-center gap-1 transition-colors duration-150 hover:text-muted",
                            ALIGN[col.align ?? "left"] === "text-right" && "flex-row-reverse"
                          )}
                        >
                          {col.header}
                          {active ? (
                            sort?.dir === "asc" ? (
                              <CaretUp size={11} weight="bold" aria-hidden />
                            ) : (
                              <CaretDown size={11} weight="bold" aria-hidden />
                            )
                          ) : (
                            <CaretDown size={11} className="opacity-30" aria-hidden />
                          )}
                        </button>
                      ) : (
                        col.header
                      )}
                    </th>
                  );
                })}
                {rowActions && <th scope="col" className="w-px text-right" />}
              </tr>
            </thead>
            <tbody>
              {safeRows.map((row) => {
                const key = rowKey(row);
                const selected = isRowSelected?.(row) ?? false;
                return (
                  <tr
                    key={key}
                    data-selected={selected || undefined}
                    onClick={onRowClick ? () => onRowClick(row) : undefined}
                    className={cn(onRowClick && "cursor-pointer")}
                    {...(rowProps?.(row) ?? {})}
                  >
                    {columns.map((col) => (
                      <td
                        key={col.key}
                        className={cn(
                          cellPad,
                          ALIGN[col.align ?? "left"],
                          col.hideBelow && HIDE[col.hideBelow],
                          col.className
                        )}
                      >
                        {col.render(row)}
                      </td>
                    ))}
                    {rowActions && (
                      <td className={cn(cellPad, "text-right whitespace-nowrap")}>
                        <span
                          className="inline-flex items-center gap-1"
                          onClick={(event) => event.stopPropagation()}
                        >
                          {rowActions(row)}
                        </span>
                      </td>
                    )}
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
      {footer && <div className="mt-3 flex flex-wrap items-center justify-between gap-3">{footer}</div>}
    </div>
  );
}

export function Pagination({
  page,
  pageSize,
  total,
  onPageChange,
  className,
}: {
  /** 1-based */
  page: number;
  pageSize: number;
  total: number;
  onPageChange: (page: number) => void;
  className?: string;
}) {
  const pages = Math.max(1, Math.ceil(total / pageSize));
  const from = total === 0 ? 0 : (page - 1) * pageSize + 1;
  const to = Math.min(page * pageSize, total);
  return (
    <nav
      aria-label="Paginación"
      className={cn("flex flex-wrap items-center justify-between gap-3", className)}
    >
      <p className="text-xs text-muted tabular-nums">
        {from}–{to} de {total}
      </p>
      <div className="flex items-center gap-1">
        <IconButton
          label="Página anterior"
          icon={CaretLeft}
          variant="secondary"
          iconSize={15}
          className="h-8 w-8 min-h-0"
          disabled={page <= 1}
          onClick={() => onPageChange(page - 1)}
        />
        <span className="px-2 text-xs text-muted tabular-nums">
          {page} / {pages}
        </span>
        <IconButton
          label="Página siguiente"
          icon={CaretRight}
          variant="secondary"
          iconSize={15}
          className="h-8 w-8 min-h-0"
          disabled={page >= pages}
          onClick={() => onPageChange(page + 1)}
        />
      </div>
    </nav>
  );
}

/** Contador de resultados con alcance de filtro. */
export function ResultCount({
  shown,
  total,
  noun = "resultados",
}: {
  shown: number;
  total: number;
  noun?: string;
}) {
  return (
    <p className="text-xs text-muted tabular-nums">
      {shown === total ? `${total} ${noun}` : `${shown} de ${total} ${noun}`}
    </p>
  );
}
