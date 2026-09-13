import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState } from "react";
import { describe, expect, it, vi } from "vitest";
import { ConditionBuilder } from "./ConditionBuilder";
import type { ConditionGroupNode } from "../../lib/conditionTree";
import type { DataSourceOption } from "../../lib/dataPicker";

const SOURCES: DataSourceOption[] = [
  {
    id: "trigger",
    label: "Cuando ocurre el evento",
    kind: "trigger",
    fields: [
      { key: "stock", label: "Stock disponible", ref: "{{trigger.stock}}", type: "number", sample: 7 },
    ],
  },
];

function Harness({ initial, onChange }: { initial: Record<string, unknown>; onChange?: (tree: ConditionGroupNode) => void }) {
  const [config, setConfig] = useState(initial);
  return (
    <ConditionBuilder
      config={config}
      sources={SOURCES}
      onChange={(tree) => {
        setConfig({ rules: tree });
        onChange?.(tree);
      }}
    />
  );
}

describe("ConditionBuilder", () => {
  it("muestra una condición legacy como fila editable", () => {
    render(<Harness initial={{ field: "trigger.stock", operator: "<", value: 10 }} />);
    expect(screen.getByTestId("wf-cond-operator-0")).toHaveValue("<");
    expect(screen.getByTestId("wf-cond-value-0")).toHaveValue("10");
  });

  it("cambia el operador y guarda el árbol", async () => {
    const user = userEvent.setup();
    const onChange = vi.fn();
    render(<Harness initial={{ field: "trigger.stock", operator: "<", value: 10 }} onChange={onChange} />);
    await user.selectOptions(screen.getByTestId("wf-cond-operator-0"), ">=");
    expect(onChange).toHaveBeenCalled();
    const tree = onChange.mock.calls[onChange.mock.calls.length - 1][0] as ConditionGroupNode;
    expect(tree.children[0]).toMatchObject({ kind: "condition", operator: ">=" });
  });

  it("oculta el valor para operadores sin valor", async () => {
    const user = userEvent.setup();
    render(<Harness initial={{ field: "trigger.stock", operator: "<", value: 10 }} />);
    expect(screen.getByTestId("wf-cond-value-0")).toBeInTheDocument();
    await user.selectOptions(screen.getByTestId("wf-cond-operator-0"), "is_empty");
    expect(screen.queryByTestId("wf-cond-value-0")).toBeNull();
  });

  it("añade condiciones y grupos anidados", async () => {
    const user = userEvent.setup();
    const onChange = vi.fn();
    render(<Harness initial={{ field: "trigger.stock", operator: "<", value: 10 }} onChange={onChange} />);
    await user.click(screen.getByTestId("wf-cond-add-root"));
    let tree = onChange.mock.calls[onChange.mock.calls.length - 1][0] as ConditionGroupNode;
    expect(tree.children).toHaveLength(2);

    await user.click(screen.getByTestId("wf-cond-add-group-root"));
    tree = onChange.mock.calls[onChange.mock.calls.length - 1][0] as ConditionGroupNode;
    expect(tree.children).toHaveLength(3);
    expect(tree.children[2].kind).toBe("group");
  });

  it("elige un dato con el Data Picker y guarda la referencia", async () => {
    const user = userEvent.setup();
    const onChange = vi.fn();
    render(<Harness initial={{}} onChange={onChange} />);
    await user.click(screen.getByTestId("wf-cond-field-0"));
    await user.click(screen.getByTestId("wf-cond-field-0-field-trigger-stock"));
    const tree = onChange.mock.calls[onChange.mock.calls.length - 1][0] as ConditionGroupNode;
    expect(tree.children[0]).toMatchObject({
      kind: "condition",
      field: "{{trigger.stock}}",
      label: "Stock disponible",
    });
    expect(screen.getByText("Stock disponible")).toBeInTheDocument();
  });

  it("cambia el grupo a 'al menos una'", async () => {
    const user = userEvent.setup();
    const onChange = vi.fn();
    render(<Harness initial={{ field: "trigger.stock", operator: "<", value: 10 }} onChange={onChange} />);
    await user.selectOptions(screen.getByTestId("wf-cond-op-root"), "or");
    const tree = onChange.mock.calls[onChange.mock.calls.length - 1][0] as ConditionGroupNode;
    expect(tree.op).toBe("or");
  });
});
