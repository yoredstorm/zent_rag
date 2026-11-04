import {
  ArrowsInSimple,
  CornersOut,
  Keyboard,
  MagnifyingGlass,
  MapTrifold,
  Minus,
  Plus,
  SelectionAll,
  TreeStructure,
} from "@phosphor-icons/react";
import type { ReactNode } from "react";
import { CANVAS_KIND_LEGEND, canvasNodeKindMeta } from "../../lib/canvasNodeKind";
import type { LayoutDirection } from "../../lib/graphAutoLayout";
import { Menu, MenuItem, Popover, Tooltip, menuItemClass } from "../ui";

const CANVAS_SHORTCUTS: [string, string][] = [
  ["Rueda / pellizco", "Zoom hacia el cursor"],
  ["Dos dedos · arrastrar fondo", "Desplazar el lienzo"],
  ["Shift + arrastrar fondo", "Selección por área"],
  ["Shift/Ctrl + clic", "Añadir o quitar de la selección"],
  ["Shift + 1", "Encuadrar todo"],
  ["Shift + 2", "Encuadrar selección"],
  ["Shift + 0", "Zoom al 100 %"],
  ["+ / −", "Acercar / alejar"],
  ["Ctrl + F", "Buscar nodo"],
  ["Flechas", "Mover selección (Shift: ×5)"],
  ["Enter", "Configurar el nodo enfocado"],
  ["Ctrl + A / Ctrl + D", "Seleccionar todo / duplicar"],
  ["Supr", "Eliminar selección"],
  ["Ctrl + Z / Ctrl + Shift + Z", "Deshacer / rehacer"],
  ["F", "Modo enfoque (Esc para salir)"],
];

function ToolButton({
  label,
  shortcut,
  onClick,
  disabled,
  pressed,
  children,
  testId,
}: {
  label: string;
  shortcut?: string;
  onClick?: () => void;
  disabled?: boolean;
  pressed?: boolean;
  children: ReactNode;
  testId?: string;
}) {
  return (
    <Tooltip label={shortcut ? `${label} · ${shortcut}` : label}>
      <button
        type="button"
        aria-label={label}
        aria-pressed={pressed}
        disabled={disabled}
        data-testid={testId}
        onClick={onClick}
        className={`flex h-8 min-w-8 cursor-pointer items-center justify-center rounded-md px-1.5 text-muted outline-none transition-colors hover:bg-soft hover:text-text focus-visible:ring-2 focus-visible:ring-accent disabled:cursor-not-allowed disabled:opacity-40 ${
          pressed ? "bg-soft text-text" : ""
        }`}
      >
        {children}
      </button>
    </Tooltip>
  );
}

type Props = {
  zoom: number;
  hasSelection: boolean;
  minimap: boolean;
  onZoomIn: () => void;
  onZoomOut: () => void;
  onResetZoom: () => void;
  onFitView: () => void;
  onFitSelection: () => void;
  onSearch: () => void;
  onLayout: (direction: LayoutDirection) => void;
  onToggleMinimap: () => void;
  extra?: ReactNode;
};

export function CanvasToolbar({
  zoom,
  hasSelection,
  minimap,
  onZoomIn,
  onZoomOut,
  onResetZoom,
  onFitView,
  onFitSelection,
  onSearch,
  onLayout,
  onToggleMinimap,
  extra,
}: Props) {
  const divider = <span className="mx-0.5 h-5 w-px bg-border" aria-hidden />;
  return (
    <div
      role="toolbar"
      aria-label="Navegación del lienzo"
      data-testid="wf-canvas-toolbar"
      className="flex items-center gap-0.5 rounded-lg border border-border bg-raised/95 p-1 shadow-pop backdrop-blur-sm"
      onPointerDown={(ev) => ev.stopPropagation()}
    >
      {extra}
      {extra && divider}
      <ToolButton label="Alejar" shortcut="−" onClick={onZoomOut} testId="wf-zoom-out">
        <Minus size={15} aria-hidden />
      </ToolButton>
      <Tooltip label="Restablecer zoom al 100 % · Shift + 0">
        <button
          type="button"
          aria-label={`Zoom ${Math.round(zoom * 100)} %, restablecer al 100 %`}
          data-testid="wf-zoom-level"
          onClick={onResetZoom}
          className="h-8 w-14 cursor-pointer rounded-md text-[12px] font-medium tabular-nums text-text outline-none hover:bg-soft focus-visible:ring-2 focus-visible:ring-accent"
        >
          {Math.round(zoom * 100)}%
        </button>
      </Tooltip>
      <ToolButton label="Acercar" shortcut="+" onClick={onZoomIn} testId="wf-zoom-in">
        <Plus size={15} aria-hidden />
      </ToolButton>
      {divider}
      <ToolButton label="Encuadrar todo" shortcut="Shift + 1" onClick={onFitView} testId="wf-fit-view">
        <CornersOut size={15} aria-hidden />
      </ToolButton>
      <ToolButton
        label="Encuadrar selección"
        shortcut="Shift + 2"
        onClick={onFitSelection}
        disabled={!hasSelection}
        testId="wf-fit-selection"
      >
        <ArrowsInSimple size={15} aria-hidden />
      </ToolButton>
      <ToolButton label="Buscar nodo" shortcut="Ctrl + F" onClick={onSearch} testId="wf-canvas-search-open">
        <MagnifyingGlass size={15} aria-hidden />
      </ToolButton>
      {divider}
      <Menu
        label="Organizar el grafo"
        align="center"
        side="top"
        trigger={
          <button
            type="button"
            aria-label="Organizar el grafo"
            title="Organizar automáticamente"
            data-testid="wf-autolayout"
            className="flex h-8 min-w-8 cursor-pointer items-center justify-center rounded-md px-1.5 text-muted outline-none hover:bg-soft hover:text-text focus-visible:ring-2 focus-visible:ring-accent"
          >
            <TreeStructure size={15} aria-hidden />
          </button>
        }
      >
        <MenuItem className={menuItemClass} data-testid="wf-autolayout-lr" onSelect={() => onLayout("LR")}>
          Ordenar en horizontal
        </MenuItem>
        <MenuItem className={menuItemClass} data-testid="wf-autolayout-tb" onSelect={() => onLayout("TB")}>
          Ordenar en vertical
        </MenuItem>
        <p className="px-2.5 pt-1 pb-1.5 text-[11px] leading-snug text-faint">
          Solo mueve nodos; las conexiones no cambian. Ctrl + Z lo deshace.
        </p>
      </Menu>
      <ToolButton label={minimap ? "Ocultar minimapa" : "Mostrar minimapa"} pressed={minimap} onClick={onToggleMinimap} testId="wf-minimap-toggle">
        <MapTrifold size={15} aria-hidden />
      </ToolButton>
      <Popover
        side="top"
        align="end"
        width={340}
        trigger={
          <button
            type="button"
            aria-label="Atajos y leyenda"
            title="Atajos y leyenda"
            data-testid="wf-shortcuts"
            className="flex h-8 min-w-8 cursor-pointer items-center justify-center rounded-md px-1.5 text-muted outline-none hover:bg-soft hover:text-text focus-visible:ring-2 focus-visible:ring-accent"
          >
            <Keyboard size={15} aria-hidden />
          </button>
        }
      >
        <p className="text-[12px] font-semibold text-text">Atajos del lienzo</p>
        <dl className="mt-2 grid grid-cols-[auto_1fr] gap-x-3 gap-y-1 text-[12px]">
          {CANVAS_SHORTCUTS.map(([keys, action]) => (
            <div key={keys} className="contents">
              <dt className="font-mono text-[11px] text-muted">{keys}</dt>
              <dd className="text-text">{action}</dd>
            </div>
          ))}
        </dl>
        <p className="mt-3 text-[12px] font-semibold text-text">Tipos de nodo</p>
        <ul className="mt-1.5 grid grid-cols-2 gap-1.5 text-[12px] text-muted">
          {CANVAS_KIND_LEGEND.map((kind) => {
            const meta = canvasNodeKindMeta(kind);
            const Icon = meta.icon;
            return (
              <li key={kind} className="flex items-center gap-1.5">
                <span className={`h-3 w-1 rounded-full ${meta.stripe}`} aria-hidden />
                <Icon size={13} className={meta.text} aria-hidden />
                {meta.label}
              </li>
            );
          })}
        </ul>
        <p className="mt-3 flex items-center gap-1.5 text-[11px] text-faint">
          <SelectionAll size={12} aria-hidden /> Alejado se muestran nodos simplificados; acercado, el detalle técnico.
        </p>
      </Popover>
    </div>
  );
}
