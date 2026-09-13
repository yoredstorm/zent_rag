/**
 * Árbol de condiciones de negocio (espejo de `workflows/conditions.py`).
 * La UI Simple edita este árbol; el nodo `condition` lo guarda en config.rules
 * y el runtime lo evalúa sin nodos extra.
 */
export type ConditionRule = {
  kind: "condition";
  field: string;
  operator: string;
  value?: unknown;
  label?: string;
};

export type ConditionGroupNode = {
  kind: "group";
  op: "and" | "or";
  children: ConditionNode[];
};

export type ConditionNode = ConditionRule | ConditionGroupNode;

export const CONDITION_OPERATORS: { value: string; label: string }[] = [
  { value: "==", label: "es" },
  { value: "!=", label: "no es" },
  { value: ">", label: "es mayor que" },
  { value: ">=", label: "es al menos" },
  { value: "<", label: "es menor que" },
  { value: "<=", label: "es como máximo" },
  { value: "contains", label: "contiene" },
  { value: "not_contains", label: "no contiene" },
  { value: "starts_with", label: "empieza con" },
  { value: "ends_with", label: "termina con" },
  { value: "is_empty", label: "está vacío" },
  { value: "not_empty", label: "no está vacío" },
  { value: "changed", label: "cambió" },
];

export const VALUELESS_OPERATORS = new Set(["is_empty", "not_empty"]);

export function operatorLabel(value: string): string {
  return CONDITION_OPERATORS.find((o) => o.value === value)?.label ?? value;
}

export function newRule(): ConditionRule {
  return { kind: "condition", field: "", operator: "==", value: "" };
}

export function newGroup(op: "and" | "or" = "and"): ConditionGroupNode {
  return { kind: "group", op, children: [newRule()] };
}

/**
 * Normaliza el config de un nodo condition al árbol de la UI: acepta `rules`
 * (nuevo), `field/operator/value` (legacy) o vacío (una condición en blanco).
 */
export function normalizeConditionConfig(config: Record<string, unknown> | null | undefined): ConditionGroupNode {
  const data = config ?? {};
  const rules = data.rules as ConditionNode | undefined;
  if (rules && (rules.kind === "group" || rules.kind === "condition")) {
    if (rules.kind === "group") {
      return { kind: "group", op: rules.op === "or" ? "or" : "and", children: rules.children ?? [] };
    }
    return { kind: "group", op: "and", children: [rules] };
  }
  if (data.field) {
    return {
      kind: "group",
      op: "and",
      children: [
        {
          kind: "condition",
          field: String(data.field),
          operator: String(data.operator ?? "=="),
          value: data.value,
        },
      ],
    };
  }
  return { kind: "group", op: "and", children: [newRule()] };
}

/** Reemplaza el nodo en `path` (índices desde la raíz). `null` lo elimina. */
export function updateAtPath(
  root: ConditionGroupNode,
  path: number[],
  next: ConditionNode | null,
): ConditionGroupNode {
  if (path.length === 0) {
    return next && next.kind === "group" ? next : { kind: "group", op: "and", children: [] };
  }
  const [head, ...rest] = path;
  const children = [...root.children];
  if (rest.length === 0) {
    if (next === null) children.splice(head, 1);
    else children[head] = next;
  } else {
    const target = children[head];
    if (!target || target.kind !== "group") return root;
    children[head] = updateAtPath(target, rest, next);
  }
  return { ...root, children };
}

export function appendToGroup(root: ConditionGroupNode, path: number[], node: ConditionNode): ConditionGroupNode {
  const pathToGroup = path.length === 0 ? [] : path;
  const group = pathToGroup.length === 0 ? root : getAtPath(root, pathToGroup);
  if (!group || group.kind !== "group") return root;
  return updateAtPath(root, pathToGroup, { ...group, children: [...group.children, node] });
}

export function getAtPath(root: ConditionGroupNode, path: number[]): ConditionNode | null {
  let current: ConditionNode = root;
  for (const index of path) {
    if (current.kind !== "group") return null;
    const child: ConditionNode | undefined = current.children[index];
    if (!child) return null;
    current = child;
  }
  return current;
}

/** Frase humana del árbol (espejo del backend para previews). */
export function describeCondition(node: ConditionNode | null | undefined): string {
  if (!node) return "";
  if (node.kind === "group") {
    const separator = node.op === "or" ? " o " : " y ";
    const parts = node.children
      .map((child) => {
        const text = describeCondition(child);
        if (!text) return "";
        return child.kind === "group" ? `(${text})` : text;
      })
      .filter(Boolean);
    return parts.join(separator);
  }
  const label = node.label || node.field || "dato";
  const op = operatorLabel(node.operator);
  if (VALUELESS_OPERATORS.has(node.operator)) return `${label} ${op}`;
  if (node.value === undefined || node.value === "") return `${label} ${op}`;
  return `${label} ${op} ${String(node.value)}`;
}
