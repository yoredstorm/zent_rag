import { memo, type KeyboardEvent, type MouseEvent, type PointerEvent } from "react";
import { NODE_H, NODE_W, type DetailLevel } from "../../lib/canvasViewport";
import { canvasNodeKindMeta, type CanvasNodeKind } from "../../lib/canvasNodeKind";
import type { LayoutDirection } from "../../lib/graphAutoLayout";
import { CATEGORY_META, nodeMeta, type GraphNode } from "../../lib/workflowGraph";
import { branchLabel, portOffset } from "./geometry";

export type RunMark = {
  status: string;
  duration_ms?: number | null;
  error?: string | null;
  simulated?: boolean;
  text?: string | null;
};

export type NodeHandlers = {
  onPointerDown: (ev: PointerEvent<HTMLDivElement>, id: string) => void;
  onPortDown: (ev: PointerEvent<HTMLSpanElement>, id: string, port: string) => void;
  onDoubleClick: (id: string) => void;
  onContextMenu: (ev: MouseEvent<HTMLDivElement>, id: string) => void;
  onKeyDown: (ev: KeyboardEvent<HTMLDivElement>, id: string) => void;
  onFocus: (id: string) => void;
};

const STATUS_BORDER: Record<string, string> = {
  succeeded: "border-ok/70",
  simulated: "border-info/70",
  skipped: "border-faint/60 opacity-70",
  failed: "border-danger/80",
  denied: "border-danger/80",
  pending_approval: "border-warn/80",
  paused: "border-warn/60",
};

const STATUS_BADGE: Record<string, string> = {
  succeeded: "badge-ok",
  failed: "badge-danger",
  denied: "badge-danger",
  skipped: "badge-muted",
};

const STATUS_TEXT: Record<string, string> = {
  succeeded: "ok",
  simulated: "simulado",
  failed: "falló",
  denied: "denegado",
  skipped: "saltado",
  pending_approval: "aprobación",
  paused: "en espera",
};

const CATEGORY_LABEL: Record<string, string> = Object.fromEntries(
  Object.entries(CATEGORY_META).map(([k, v]) => [k, v.label]),
);

type Props = {
  node: GraphNode;
  x: number;
  y: number;
  kind: CanvasNodeKind;
  direction: LayoutDirection;
  lod: DetailLevel;
  /** Zoom actual: solo se usa en vista general para escalar la etiqueta. */
  overviewScale: number;
  selected: boolean;
  primary: boolean;
  run?: RunMark;
  issue?: { status: string; message: string };
  agentName?: string;
  hotInPort: string | null;
  wiringPort: string | null;
  handlers: NodeHandlers;
};

function CanvasNodeView({
  node: n,
  x,
  y,
  kind,
  direction,
  lod,
  overviewScale,
  selected,
  primary,
  run,
  issue,
  agentName,
  hotInPort,
  wiringPort,
  handlers,
}: Props) {
  const meta = nodeMeta(n.type);
  const kindMeta = canvasNodeKindMeta(kind);
  const KindIcon = kindMeta.icon;
  const title = n.label || meta.label;
  const needsAgent = n.type === "llm" && !n.config.agent_id;
  const subtitle =
    n.type === "llm"
      ? agentName
        ? `Agente: ${agentName}`
        : needsAgent
          ? "Falta elegir agente"
          : "Agente configurado"
      : title !== meta.label
        ? meta.label
        : CATEGORY_LABEL[meta.category];
  const detail =
    n.type === "llm" ? String(n.config.prompt ?? "").trim() || "sin pregunta" : (meta.summary?.(n.config) ?? "sin configurar");
  const statusLabel = run ? STATUS_TEXT[run.status] ?? run.status : "";
  const ariaLabel = [title, kindMeta.label, statusLabel && `estado ${statusLabel}`, issue && issue.message]
    .filter(Boolean)
    .join(", ");

  return (
    <div
      data-testid="wf-canvas-node"
      data-node-id={n.id}
      data-kind={kind}
      data-lod={lod}
      role="button"
      tabIndex={0}
      aria-label={ariaLabel}
      aria-pressed={selected}
      className={`absolute select-none border bg-surface shadow-panel outline-none transition-[border-color,box-shadow] duration-150 focus-visible:ring-2 focus-visible:ring-accent ${kindMeta.shape} ${
        selected ? `border-accent ${primary ? "ring-2 ring-accent/40" : "ring-1 ring-accent/25"}` : "border-border hover:border-border-strong"
      } ${STATUS_BORDER[run?.status ?? ""] ?? ""}`}
      style={{ left: x, top: y, width: NODE_W, height: NODE_H }}
      onPointerDown={(ev) => handlers.onPointerDown(ev, n.id)}
      onDoubleClick={() => handlers.onDoubleClick(n.id)}
      onContextMenu={(ev) => handlers.onContextMenu(ev, n.id)}
      onKeyDown={(ev) => handlers.onKeyDown(ev, n.id)}
      onFocus={() => handlers.onFocus(n.id)}
    >
      <div className="absolute inset-0 flex flex-col overflow-hidden rounded-[inherit]">
      <span className={`pointer-events-none absolute inset-y-0 left-0 w-1 ${kindMeta.stripe}`} aria-hidden />
      {lod === "overview" ? (
        <div className="flex h-full items-center gap-3 pr-3 pl-4">
          <KindIcon size={34} weight="duotone" className={`shrink-0 ${kindMeta.text}`} aria-hidden />
          <span
            className="line-clamp-2 min-w-0 font-semibold leading-tight text-text"
            style={{ fontSize: Math.min(30, 13 / Math.max(0.2, overviewScale)) }}
          >
            {title}
          </span>
        </div>
      ) : (
        <>
          <div className="flex items-center gap-2 border-b border-border-soft py-2 pr-2.5 pl-3.5">
            <span
              className="flex h-7 w-7 shrink-0 items-center justify-center rounded-sm border border-border-soft bg-soft"
              data-canvas-role={kind}
              title={kindMeta.label}
              aria-hidden
            >
              <KindIcon size={15} weight="regular" className={kindMeta.text} />
            </span>
            <span className="min-w-0 flex-1">
              <span className="block truncate text-[13px] leading-tight font-semibold text-text">{title}</span>
              <span
                className={`block truncate text-[11px] leading-tight ${needsAgent ? "text-warn" : "text-faint"}`}
                data-testid={needsAgent ? "wf-node-needs-agent" : undefined}
              >
                {subtitle}
              </span>
            </span>
            {run && (
              <span className={`badge shrink-0 ${STATUS_BADGE[run.status] ?? "badge-pending"}`}>{statusLabel}</span>
            )}
            {issue && (
              <span
                className={`badge shrink-0 ${issue.status === "error" ? "badge-danger" : "badge-pending"}`}
                data-testid="wf-node-issue"
                title={issue.message}
              >
                {issue.status === "error" ? "falta" : "revisar"}
              </span>
            )}
          </div>
          <div className="min-h-0 flex-1 py-1.5 pr-2.5 pl-3.5">
            {run?.error ? (
              <p className="line-clamp-2 text-[11px] leading-snug text-danger" data-testid="wf-node-error">
                {run.error}
              </p>
            ) : run?.text ? (
              <p className="line-clamp-2 text-[11px] leading-snug text-muted" data-testid="wf-node-answer">
                “{run.text}”
              </p>
            ) : (
              <p className="line-clamp-2 text-[11px] leading-snug text-muted">{detail}</p>
            )}
            {lod === "detail" && (
              <p className="mt-0.5 truncate font-mono text-[9px] text-faint">
                {n.id}
                {run?.duration_ms != null ? ` · ${run.duration_ms} ms` : ""}
              </p>
            )}
          </div>
        </>
      )}
      </div>

      {n.input_ports.map((p, i) => {
        const off = portOffset(i, n.input_ports.length, "in", direction);
        return (
          <span
            key={`in-${p.name}`}
            data-port
            data-node={n.id}
            data-port-name={p.name}
            data-side="in"
            aria-hidden
            className={`absolute h-3 w-3 -translate-x-1/2 -translate-y-1/2 rounded-full border-2 border-raised ${
              hotInPort === p.name ? "scale-125 bg-ok" : "bg-faint"
            }`}
            style={{ left: off.x, top: off.y }}
          />
        );
      })}
      {n.output_ports.map((p, i) => {
        const off = portOffset(i, n.output_ports.length, "out", direction);
        const branch = n.output_ports.length > 1 ? branchLabel(p.name) : null;
        return (
          <span key={`out-${p.name}`}>
            <span
              data-port
              data-node={n.id}
              data-port-name={p.name}
              data-side="out"
              aria-hidden
              title={`Conectar salida ${branch ?? p.name}`}
              onPointerDown={(ev) => handlers.onPortDown(ev, n.id, p.name)}
              className={`absolute h-3.5 w-3.5 -translate-x-1/2 -translate-y-1/2 cursor-crosshair rounded-full border-2 border-raised ${
                wiringPort === p.name ? "bg-accent shadow-glow" : "bg-accent/70 hover:scale-125 hover:bg-accent"
              }`}
              style={{ left: off.x, top: off.y }}
            />
            {branch && lod !== "overview" && (
              <span
                className="pointer-events-none absolute text-[10px] font-medium text-faint"
                style={
                  direction === "TB"
                    ? { left: off.x - 8, top: off.y - 18 }
                    : { left: off.x - 22, top: off.y - 7 }
                }
              >
                {branch}
              </span>
            )}
          </span>
        );
      })}
    </div>
  );
}

export const CanvasNode = memo(CanvasNodeView);
