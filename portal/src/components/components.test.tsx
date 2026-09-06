import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it } from "vitest";
import { AttentionList } from "./AttentionList";
import { Breadcrumb } from "./Breadcrumb";
import { PageTabs } from "./PageTabs";
import { Stepper } from "./Stepper";
import { Timeline } from "./Timeline";
import { expectAxeToHaveNoViolations } from "../test/axe";

describe("AttentionList", () => {
  it("muestra los ítems con CTA", () => {
    render(
      <MemoryRouter>
        <AttentionList items={[{ id: "1", label: "Fuente rota", to: "/knowledge/sources" }]} />
      </MemoryRouter>
    );
    expect(screen.getByText("Fuente rota")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Revisar" })).toHaveAttribute("href", "/knowledge/sources");
  });

  it("muestra estado vacío", () => {
    render(
      <MemoryRouter>
        <AttentionList items={[]} emptyTitle="Todo en orden" />
      </MemoryRouter>
    );
    expect(screen.getByText("Todo en orden")).toBeInTheDocument();
  });
});

describe("Breadcrumb", () => {
  it("renderiza la miga y marca el último como actual", () => {
    render(
      <MemoryRouter>
        <Breadcrumb items={[{ label: "Agentes", to: "/agents" }, { label: "Mi agente" }]} />
      </MemoryRouter>
    );
    expect(screen.getByRole("link", { name: "Agentes" })).toHaveAttribute("href", "/agents");
    expect(screen.getByText("Mi agente")).toBeInTheDocument();
  });
});

describe("PageTabs", () => {
  it("expone role=tablist/tab y aria-selected", () => {
    const onChange = () => {};
    render(
      <PageTabs
        idPrefix="t"
        tabs={[{ id: "a", label: "A" }, { id: "b", label: "B" }]}
        active="a"
        onChange={onChange}
      />
    );
    expect(screen.getByRole("tablist")).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: "A" })).toHaveAttribute("aria-selected", "true");
    expect(screen.getByRole("tab", { name: "B" })).toHaveAttribute("aria-selected", "false");
  });
});

describe("Stepper", () => {
  it("marca la etapa activa con aria-current", () => {
    render(
      <Stepper
        steps={[{ id: "a", label: "A" }, { id: "b", label: "B" }]}
        active="b"
        onSelect={() => {}}
      />
    );
    expect(screen.getByRole("button", { name: /B/ })).toHaveAttribute("aria-current", "step");
  });

  it("sin violaciones de accesibilidad", async () => {
    const { container } = render(
      <Stepper
        steps={[{ id: "a", label: "A" }, { id: "b", label: "B" }]}
        active="a"
        onSelect={() => {}}
      />
    );
    await expectAxeToHaveNoViolations(container);
  });
});

describe("Timeline", () => {
  it("agrupa por día y ordena desc", () => {
    const { container } = render(
      <Timeline
        items={[
          { id: "1", at: "2026-09-01T10:00:00Z", title: "Deploy v2", kind: "deployment", tone: "ok" },
          { id: "2", at: "2026-09-01T08:00:00Z", title: "Sync postgres", kind: "job" },
        ]}
      />
    );
    expect(screen.getByText("Deploy v2")).toBeInTheDocument();
    expect(screen.getByText("Sync postgres")).toBeInTheDocument();
    const items = container.querySelectorAll("li");
    expect(items.length).toBe(2);
  });

  it("muestra vacío sin eventos", () => {
    render(<Timeline items={[]} />);
    expect(screen.getByText("Sin actividad registrada.")).toBeInTheDocument();
  });
});