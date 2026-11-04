import { fireEvent, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";
import { NodeConfigPanel } from "./NodeConfigPanel";
import type { NodeBusinessSchema } from "../lib/businessSchema";
import type { GraphNode, WorkflowGraph } from "../lib/workflowGraph";
import type { RunDetail } from "./WorkflowRunInspector";

vi.mock("../auth", () => ({
  useAuth: () => ({ session: { token: "t", organizationId: "org" } }),
}));

function node(partial: Partial<GraphNode> & { id: string; type: string }): GraphNode {
  return {
    version: 1,
    label: partial.type,
    position: { x: 0, y: 0 },
    config: {},
    input_ports: [{ name: "in", type: "json" }],
    output_ports: [{ name: "out", type: "json" }],
    retry_policy: { max_attempts: 1 },
    timeout_ms: 60000,
    error_policy: "fail",
    metadata: {},
    ...partial,
  };
}

const NOTIFY = node({ id: "n1", type: "notify", label: "Avisar", config: { channel: "in_app", title: "Stock bajo" } });
const GRAPH: WorkflowGraph = {
  workflow_version: 2,
  nodes: [node({ id: "t", type: "trigger_webhook" }), NOTIFY],
  edges: [{ id: "e1", from_node: "t", from_port: "out", to_node: "n1", to_port: "in" }],
  variables: {},
  entrypoints: ["t"],
  metadata: {},
};

const RUN: RunDetail = {
  id: "run-1",
  status: "succeeded",
  duration_ms: 284,
  steps: [
    {
      step_index: 1,
      step_type: "notify",
      node_id: "n1",
      node_type: "notify",
      status: "succeeded",
      input: { channel: "in_app", title: "Stock bajo" },
      output: { sent: true, channel: "in_app" },
      duration_ms: 120,
      retries: 0,
    },
  ],
};

function renderPanel(props: Record<string, unknown> = {}) {
  return render(
    <MemoryRouter>
      <NodeConfigPanel
        graph={GRAPH}
        node={NOTIFY}
        edge={null}
        onChange={() => undefined}
        onDeleteNode={() => undefined}
        onDeleteEdge={() => undefined}
        kbs={[]}
        agents={[]}
        run={RUN}
        {...props}
      />
    </MemoryRouter>,
  );
}

describe("NodeConfigPanel tabs", () => {
  it("muestra Configurar por defecto y Avanzado colapsado", async () => {
    renderPanel();
    expect(screen.getByTestId("wf-tab-config")).toHaveAttribute("aria-selected", "true");
    expect(screen.getByTestId("wf-advanced")).toBeInTheDocument();
    expect(screen.getByTestId("wf-advanced")).not.toHaveAttribute("open");
  });

  it("Output muestra la salida real del último run y no JSON crudo", async () => {
    const user = userEvent.setup();
    renderPanel();
    await user.click(screen.getByTestId("wf-tab-output"));
    expect(screen.getByTestId("wf-output-view")).toHaveTextContent("Enviado");
    expect(screen.getByTestId("wf-output-view")).toHaveTextContent("Sí");
    expect(screen.queryByTestId("wf-output-view-json")).toBeNull();
  });

  it("Run muestra estado, duración y acciones parciales", async () => {
    const user = userEvent.setup();
    const onRunPartial = vi.fn();
    renderPanel({ onRunPartial });
    await user.click(screen.getByTestId("wf-tab-run"));
    expect(screen.getByTestId("wf-node-run")).toHaveTextContent("succeeded");
    expect(screen.getByTestId("wf-node-run")).toHaveTextContent("120 ms");
    await user.click(screen.getByTestId("wf-run-node"));
    expect(onRunPartial).toHaveBeenCalledWith("n1", "node");
    await user.click(screen.getByTestId("wf-run-until"));
    expect(onRunPartial).toHaveBeenCalledWith("n1", "until_node");
    await user.click(screen.getByTestId("wf-run-from"));
    expect(onRunPartial).toHaveBeenCalledWith("n1", "from_node");
  });

  it("Input muestra la entrada registrada del run", async () => {
    const user = userEvent.setup();
    renderPanel();
    await user.click(screen.getByTestId("wf-tab-input"));
    expect(screen.getByTestId("wf-node-input")).toHaveTextContent("Canal");
    expect(screen.getByTestId("wf-node-input")).toHaveTextContent("Stock bajo");
  });

  it("Output permite fijar datos para pruebas", async () => {
    const user = userEvent.setup();
    const onPinData = vi.fn();
    renderPanel({ onPinData });
    await user.click(screen.getByTestId("wf-tab-output"));
    await user.click(screen.getByTestId("wf-pin-data"));
    expect(onPinData).toHaveBeenCalledWith("n1", { sent: true, channel: "in_app" });
  });

  it("muestra el badge de datos fijados y permite quitarlos", async () => {
    const user = userEvent.setup();
    const onUnpinData = vi.fn();
    renderPanel({ pinned: true, onUnpinData });
    await user.click(screen.getByTestId("wf-tab-output"));
    expect(screen.getByTestId("wf-pinned-badge")).toHaveTextContent("Datos fijados");
    await user.click(screen.getByTestId("wf-unpin-data"));
    expect(onUnpinData).toHaveBeenCalledWith("n1");
  });
});

describe("NodeConfigPanel etiqueta", () => {
  it("muestra la nota de negocio del nodo", () => {
    const withNote = node({
      id: "n1",
      type: "notify",
      label: "Confirmación · Pedir",
      metadata: { note: "Paso común para delivery y recojo." },
    });
    renderPanel({ node: withNote });
    expect(screen.getByTestId("wf-node-note")).toHaveTextContent(
      "Paso común para delivery y recojo.",
    );
  });

  it("renombra el paso sin cambiar su tipo técnico", () => {
    const onChange = vi.fn();
    renderPanel({ onChange });
    fireEvent.change(screen.getByLabelText("Nombre del paso"), {
      target: { value: "Guardar cliente" },
    });
    const next = onChange.mock.calls.at(-1)?.[0] as WorkflowGraph;
    const changed = next.nodes.find((item) => item.id === "n1");
    expect(changed?.label).toBe("Guardar cliente");
    expect(changed?.type).toBe("notify");
  });
});

describe("NodeConfigPanel eventos", () => {
  it("el trigger usa el catálogo backend y muestra conversation.message", () => {
    const trigger = node({
      id: "t",
      type: "trigger_event",
      label: "Mensaje del cliente",
      config: { event_type: "conversation.message" },
    });
    const schema: NodeBusinessSchema = {
      node_type: "trigger_event",
      label: "Cuando ocurra algo",
      category: "trigger",
      risk_level: "normal",
      parameters: [
        {
          key: "event_type",
          label: "Evento",
          type: "enum",
          required: true,
          default: "source.synced",
          examples: [],
          advanced: false,
          min_level: "simple",
          secret: false,
          dynamic_options: "event_types",
          data_source: null,
          unit: null,
          validation: {},
          help: null,
          business_group: null,
        },
      ],
      outputs: [],
    };
    renderPanel({
      graph: { ...GRAPH, nodes: [trigger, NOTIFY] },
      node: trigger,
      nodeSchemas: { trigger_event: schema },
      eventOptions: [
        {
          value: "conversation.message",
          label: "Un cliente envió un mensaje (conversation.message)",
        },
      ],
    });
    expect(screen.getByTestId("wf-param-event_type")).toHaveValue("conversation.message");
    expect(
      screen.getByRole("option", { name: "Un cliente envió un mensaje (conversation.message)" }),
    ).toBeInTheDocument();
  });
});

describe("NodeConfigPanel inspector", () => {
  it("Entradas lista los puertos y navega al nodo conectado", async () => {
    const user = userEvent.setup();
    const onFocusNode = vi.fn();
    renderPanel({ onFocusNode });
    await user.click(screen.getByTestId("wf-tab-input"));
    const ports = screen.getByTestId("wf-ports-in");
    expect(ports).toHaveTextContent("in");
    expect(ports).toHaveTextContent("json");
    await user.click(screen.getByRole("button", { name: "desde trigger_webhook" }));
    expect(onFocusNode).toHaveBeenCalledWith("t");
  });

  it("Validación junta readiness, el error del último run y entradas sin conectar", async () => {
    const user = userEvent.setup();
    const orphan = node({ id: "n2", type: "notify", label: "Suelto" });
    const graph = { ...GRAPH, nodes: [...GRAPH.nodes, orphan] };
    const run: RunDetail = {
      id: "r",
      status: "failed",
      steps: [{ step_index: 0, step_type: "notify", node_id: "n2", status: "failed", error: "SMTP caído" }],
    };
    renderPanel({ graph, node: orphan, run, nodeIssue: { status: "error", message: "Falta el destinatario" } });
    const tab = screen.getByTestId("wf-tab-validation");
    expect(tab).toHaveTextContent("3");
    await user.click(tab);
    const list = screen.getByTestId("wf-node-validation");
    expect(list).toHaveTextContent("Falta el destinatario");
    expect(list).toHaveTextContent("Último run: SMTP caído");
    expect(list).toHaveTextContent("No está conectado al trigger");
    expect(list).not.toHaveTextContent("Nada llega a este nodo");
  });

  it("un nodo final sin entradas conectadas avisa en validación", async () => {
    const user = userEvent.setup();
    const end = node({ id: "z", type: "end", label: "Fin" });
    renderPanel({ graph: { ...GRAPH, nodes: [...GRAPH.nodes, end] }, node: end, run: null });
    await user.click(screen.getByTestId("wf-tab-validation"));
    expect(screen.getByTestId("wf-node-validation")).toHaveTextContent("Nada llega a este nodo");
  });

  it("sin problemas lo dice explícitamente", async () => {
    const user = userEvent.setup();
    renderPanel();
    await user.click(screen.getByTestId("wf-tab-validation"));
    expect(screen.getByTestId("wf-node-valid")).toBeInTheDocument();
  });

  it("tabRequest abre la pestaña pedida desde el lienzo y colapsar avisa al padre", async () => {
    const user = userEvent.setup();
    const onCollapse = vi.fn();
    renderPanel({ tabRequest: { tab: "run", key: 1 }, onCollapse });
    expect(screen.getByTestId("wf-tab-run")).toHaveAttribute("aria-selected", "true");
    await user.click(screen.getByTestId("wf-inspector-collapse"));
    expect(onCollapse).toHaveBeenCalled();
  });
});
