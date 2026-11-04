/**
 * Familia visual del nodo en el lienzo. Parte del rol de negocio
 * (`resolveCanvasRole`, espejo del backend) y solo separa «aprobación» de
 * «espera», que el rol agrupa pero el usuario necesita distinguir al leer
 * un proceso largo. No cambia ningún dato del grafo.
 */
import { SealCheck, type Icon } from "@phosphor-icons/react";
import { CANVAS_ROLE_META, resolveCanvasRole, type CanvasRole } from "./canvasRole";
import type { GraphNode } from "./workflowGraph";

export type CanvasNodeKind = CanvasRole | "approval";

export type CanvasNodeKindMeta = {
  label: string;
  icon: Icon;
  /** Color del icono/texto de familia. */
  text: string;
  /** Franja lateral del nodo (mismo tono que `text`). */
  stripe: string;
  /** Silueta: inicio y fin redondeados hacia afuera para leer el flujo. */
  shape: string;
};

const STRIPE: Record<CanvasRole, string> = {
  trigger: "bg-info",
  ai: "bg-purple-400",
  data: "bg-accent",
  decision: "bg-warn",
  action: "bg-fuchsia-400",
  wait: "bg-muted",
  payment: "bg-ok",
  business_result: "bg-emerald-400",
  end: "bg-faint",
};

const SHAPE: Partial<Record<CanvasNodeKind, string>> = {
  trigger: "rounded-l-2xl rounded-r-lg",
  end: "rounded-l-lg rounded-r-2xl",
};

export function canvasNodeKind(node: Pick<GraphNode, "id" | "type" | "config" | "metadata">, graphMetadata?: Record<string, unknown> | null): CanvasNodeKind {
  if (node.type === "human_approval") return "approval";
  return resolveCanvasRole(node, graphMetadata);
}

export function canvasNodeKindMeta(kind: CanvasNodeKind): CanvasNodeKindMeta {
  if (kind === "approval") {
    return { label: "Aprobación", icon: SealCheck, text: "text-orange-400", stripe: "bg-orange-400", shape: "rounded-lg" };
  }
  const role = CANVAS_ROLE_META[kind];
  return { label: role.label, icon: role.icon, text: role.color, stripe: STRIPE[kind], shape: SHAPE[kind] ?? "rounded-lg" };
}

/** Orden de la leyenda del lienzo. */
export const CANVAS_KIND_LEGEND: CanvasNodeKind[] = [
  "trigger",
  "ai",
  "data",
  "decision",
  "action",
  "wait",
  "approval",
  "payment",
  "business_result",
  "end",
];
