/**
 * Rol visual de un nodo del canvas — espejo de
 * `src/platform/commerce/sales_funnel.py::canvas_role`.
 *
 * El backend manda el rol en `node.metadata.canvas_role` y el mapa completo en
 * `graph.metadata.canvas.roles`. Cuando falta, se deriva del tipo y la
 * configuración con el mismo criterio, para que el canvas nunca pierda la
 * iconografía por familia (trigger, ai, data, decision, action, wait, payment,
 * business_result, end).
 */

import {
  Brain,
  Clock,
  CreditCard,
  CursorClick,
  Database,
  Flag,
  GitBranch,
  Lightning,
  Trophy,
  type Icon,
} from "@phosphor-icons/react";

export type CanvasRole =
  | "trigger"
  | "ai"
  | "data"
  | "decision"
  | "action"
  | "wait"
  | "payment"
  | "business_result"
  | "end";

export type CanvasRoleMeta = {
  /** Etiqueta humana del rol (tooltip / leyenda). */
  label: string;
  /** Icono único por familia; el mismo tamaño en todos los nodos. */
  icon: Icon;
  /** Un solo color de acento por familia (discreto, sin saturar). */
  color: string;
};

export const CANVAS_ROLE_META: Record<CanvasRole, CanvasRoleMeta> = {
  trigger: { label: "Inicio", icon: Lightning, color: "text-info" },
  ai: { label: "IA", icon: Brain, color: "text-purple-400" },
  data: { label: "Datos", icon: Database, color: "text-accent" },
  decision: { label: "Decisión", icon: GitBranch, color: "text-warn" },
  action: { label: "Acción", icon: CursorClick, color: "text-fuchsia-400" },
  // Espera: reloj + neutro para no confundirse con acción ni pago.
  wait: { label: "Espera", icon: Clock, color: "text-muted" },
  payment: { label: "Pago", icon: CreditCard, color: "text-ok" },
  business_result: { label: "Resultado de negocio", icon: Trophy, color: "text-emerald-400" },
  end: { label: "Fin", icon: Flag, color: "text-faint" },
};

const CANVAS_ROLES = new Set<string>(Object.keys(CANVAS_ROLE_META));

export function isCanvasRole(value: unknown): value is CanvasRole {
  return typeof value === "string" && CANVAS_ROLES.has(value);
}

export type CanvasRoleNode = {
  id?: string;
  type: string;
  config?: Record<string, unknown> | null;
  metadata?: Record<string, unknown> | null;
};

const TRIGGER_TYPES = new Set(["trigger_event", "trigger_webhook", "trigger_schedule"]);
const AI_TYPES = new Set(["llm", "ai_decision"]);
const WAIT_TYPES = new Set(["human_approval"]);
const DATA_TYPES = new Set(["kb_query", "query_business_data"]);
const STATE_TYPES = new Set([
  "state_get",
  "state_set",
  "state_merge",
  "state_append",
  "state_remove",
  "set_variable",
]);
const END_TYPES = new Set(["end", "stop"]);
const CAPABILITY_TYPES = new Set(["capability_call", "payment", "payment_checkout"]);

/** Rol derivado del nodo cuando el backend no lo manda. */
function roleFromNode(node: CanvasRoleNode): CanvasRole {
  const config = node.config ?? {};
  const type = node.type;
  if (TRIGGER_TYPES.has(type)) return "trigger";
  if (AI_TYPES.has(type)) return "ai";
  if (type === "wait_event") {
    return String(config.preset ?? "") === "payment" ? "payment" : "wait";
  }
  if (WAIT_TYPES.has(type)) return "wait";
  if (type === "condition" || type === "adaptive_route") return "decision";
  if (END_TYPES.has(type)) return "end";
  if (type === "business_result") return "business_result";
  if (CAPABILITY_TYPES.has(type)) {
    const capability = String(config.capability ?? "");
    if (capability.startsWith("catalog.") || capability.startsWith("inventory.")) return "data";
    if (capability.startsWith("payments.")) return "payment";
    return "action";
  }
  if (STATE_TYPES.has(type) || DATA_TYPES.has(type)) return "data";
  // Nodos con efecto (notify, api_call, marketplace_action, business_node,
  // control de flujo): familia de acción.
  return "action";
}

/** `graph.metadata.canvas.roles` → mapa node_id → rol (si el grafo lo trae). */
function canvasRolesOf(
  graphMetadata: Record<string, unknown> | null | undefined,
): Record<string, unknown> | null {
  const canvas = graphMetadata?.canvas;
  if (!canvas || typeof canvas !== "object") return null;
  const roles = (canvas as Record<string, unknown>).roles;
  if (!roles || typeof roles !== "object") return null;
  return roles as Record<string, unknown>;
}

/** Rol del nodo: metadata del nodo → roles del grafo → derivado del tipo. */
export function resolveCanvasRole(
  node: CanvasRoleNode,
  graphMetadata?: Record<string, unknown> | null,
): CanvasRole {
  const own = node.metadata?.canvas_role;
  if (isCanvasRole(own)) return own;
  if (node.id) {
    const shared = canvasRolesOf(graphMetadata)?.[node.id];
    if (isCanvasRole(shared)) return shared;
  }
  return roleFromNode(node);
}
