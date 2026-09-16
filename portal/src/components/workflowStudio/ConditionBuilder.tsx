/**
 * ConditionBuilder — reglas de negocio en Simple Mode:
 *   CUANDO [dato] [operador] [valor] (unidad)
 * con grupos AND/OR anidados. Guarda `config.rules`; el runtime lo evalúa.
 * Advanced conserva field/operator/value y el JSON crudo.
 */
import { Plus, Trash, X } from "@phosphor-icons/react";
import { useMemo, useState } from "react";
import type { DataFieldOption, DataSourceOption } from "../../lib/dataPicker";
import {
  CONDITION_OPERATORS,
  VALUELESS_OPERATORS,
  describeCondition,
  normalizeConditionConfig,
  updateAtPath,
  type ConditionGroupNode,
  type ConditionNode,
  type ConditionRule,
  appendToGroup,
  newGroup,
  newRule,
} from "../../lib/conditionTree";
import { Button, Input, Select } from "../ui";
import { DataPicker } from "./DataPicker";

type Props = {
  config: Record<string, unknown>;
  sources: DataSourceOption[];
  /** Emite el árbol raíz listo para persistir en config.rules. */
  onChange: (tree: ConditionGroupNode) => void;
};

export function ConditionBuilder({ config, sources, onChange }: Props) {
  const tree = useMemo(() => normalizeConditionConfig(config), [config]);
  return (
    <div className="space-y-2.5" data-testid="wf-condition-builder">
      <GroupView node={tree} path={[]} depth={0} root={tree} sources={sources} onChange={onChange} />
      {describeCondition(tree) && (
        <p
          className="rounded-md border border-accent-line bg-accent-soft/60 px-2.5 py-2 text-[12px] leading-relaxed text-muted"
          data-testid="wf-condition-preview"
        >
          Se ejecutará cuando {describeCondition(tree)}.
        </p>
      )}
    </div>
  );
}

type GroupProps = {
  node: ConditionGroupNode;
  path: number[];
  depth: number;
  root: ConditionGroupNode;
  sources: DataSourceOption[];
  onChange: (tree: ConditionGroupNode) => void;
};

function GroupView({ node, path, depth, root, sources, onChange }: GroupProps) {
  const update = (nextPath: number[], next: ConditionNode | null) => onChange(updateAtPath(root, nextPath, next));
  return (
    <div className={depth > 0 ? "space-y-2 rounded-md border border-dashed border-border-strong p-2.5" : "space-y-2"}>
      <div className="flex items-center gap-1.5">
        <Select
          className="min-h-8 w-auto text-[12px]"
          value={node.op}
          data-testid={`wf-cond-op-${path.join("-") || "root"}`}
          aria-label="Todas o alguna condición"
          onChange={(e) => update(path, { ...node, op: e.target.value === "or" ? "or" : "and" })}
        >
          <option value="and">Se cumplen todas</option>
          <option value="or">Se cumple al menos una</option>
        </Select>
        {depth > 0 && (
          <Button
            variant="ghost"
            size="sm"
            className="h-7 w-7 min-h-0 px-0 text-danger"
            aria-label="Quitar grupo"
            data-testid={`wf-cond-remove-group-${path.join("-")}`}
            onClick={() => update(path, null)}
          >
            <X size={12} aria-hidden />
          </Button>
        )}
      </div>

      {node.children.map((child, index) =>
        child.kind === "group" ? (
          <GroupView
            key={`group-${index}`}
            node={child}
            path={[...path, index]}
            depth={depth + 1}
            root={root}
            sources={sources}
            onChange={onChange}
          />
        ) : (
          <ConditionRow
            key={`cond-${index}`}
            rule={child}
            path={[...path, index]}
            sources={sources}
            onUpdate={(next) => update([...path, index], next)}
          />
        ),
      )}

      <div className="flex flex-wrap gap-1.5">
        <Button
          variant="ghost"
          size="sm"
          leadingIcon={Plus}
          className="text-[11px]"
          data-testid={`wf-cond-add-${path.join("-") || "root"}`}
          onClick={() => update(path, appendToGroup(root, path, newRule()))}
        >
          Condición
        </Button>
        {depth < 2 && (
          <Button
            variant="ghost"
            size="sm"
            leadingIcon={Plus}
            className="text-[11px]"
            data-testid={`wf-cond-add-group-${path.join("-") || "root"}`}
            onClick={() => update(path, appendToGroup(root, path, newGroup("or")))}
          >
            Grupo (Y/O)
          </Button>
        )}
      </div>
    </div>
  );
}

type RowProps = {
  rule: ConditionRule;
  path: number[];
  sources: DataSourceOption[];
  onUpdate: (next: ConditionRule | null) => void;
};

function ConditionRow({ rule, path, sources, onUpdate }: RowProps) {
  const [pickedLabel, setPickedLabel] = useState<string | null>(rule.label ?? null);
  let selected: { source: DataSourceOption; field: DataFieldOption } | null = null;
  for (const source of sources) {
    const found = source.fields.find((f) => f.ref === rule.field);
    if (found) {
      selected = { source, field: found };
      break;
    }
  }

  const displayLabel = pickedLabel ?? selected?.field.label ?? (rule.field || "Elegir dato");
  const valueless = VALUELESS_OPERATORS.has(rule.operator);

  return (
    <div className="space-y-1.5 rounded-md border border-border bg-soft/50 p-2" data-testid={`wf-cond-row-${path.join("-")}`}>
      <div className="flex items-center gap-1">
        <DataPicker
          sources={sources}
          label={displayLabel.length > 22 ? `${displayLabel.slice(0, 21)}…` : displayLabel}
          testId={`wf-cond-field-${path.join("-")}`}
          onPick={(field: DataFieldOption) => {
            setPickedLabel(field.label);
            onUpdate({ ...rule, field: field.ref, label: field.label });
          }}
        />
        {rule.field && (
          <Button
            variant="ghost"
            size="sm"
            className="h-7 w-7 min-h-0 px-0 text-faint"
            aria-label="Quitar dato"
            onClick={() => {
              setPickedLabel(null);
              onUpdate({ ...rule, field: "", label: undefined });
            }}
          >
            <X size={11} aria-hidden />
          </Button>
        )}
        <Button
          variant="ghost"
          size="sm"
          className="ml-auto h-7 w-7 min-h-0 px-0 text-danger"
          aria-label="Eliminar condición"
          data-testid={`wf-cond-delete-${path.join("-")}`}
          onClick={() => onUpdate(null)}
        >
          <Trash size={12} aria-hidden />
        </Button>
      </div>

      <div className="flex items-center gap-1.5">
        <Select
          className="min-w-0 flex-1 text-[12px]"
          value={rule.operator}
          aria-label="Operador"
          data-testid={`wf-cond-operator-${path.join("-")}`}
          onChange={(e) => {
            const operator = e.target.value;
            onUpdate({
              ...rule,
              operator,
              value: VALUELESS_OPERATORS.has(operator) ? undefined : rule.value,
            });
          }}
        >
          {CONDITION_OPERATORS.map((op) => (
            <option key={op.value} value={op.value}>{op.label}</option>
          ))}
        </Select>
        {!valueless && (
          <Input
            className="w-24 text-[12px]"
            placeholder="Valor"
            aria-label="Valor"
            data-testid={`wf-cond-value-${path.join("-")}`}
            value={rule.value === undefined || rule.value === null ? "" : String(rule.value)}
            onChange={(e) => {
              const raw = e.target.value;
              const num = Number(raw);
              onUpdate({ ...rule, value: raw !== "" && Number.isFinite(num) && /^-?\d+(\.\d+)?$/.test(raw) ? num : raw });
            }}
          />
        )}
      </div>
    </div>
  );
}
