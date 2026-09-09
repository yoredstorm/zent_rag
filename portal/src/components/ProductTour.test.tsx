import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { Session } from "../api";
import { expectAxeToHaveNoViolations } from "../test/axe";
import {
  PRODUCT_TOUR_STORAGE_KEY,
  TOUR_STEPS,
  markCompleted,
  requestProductTourStart,
} from "../lib/productTour";
import { ProductTour, ProductTourRoot } from "./ProductTour";

const STEPS = [
  {
    id: "a",
    target: "tour-a",
    title: "Paso A",
    body: "Cuerpo del paso A para el tutorial.",
  },
  {
    id: "b",
    target: "tour-b",
    title: "Paso B",
    body: "Cuerpo del paso B para el tutorial.",
  },
  {
    id: "c",
    target: "tour-c",
    title: "Paso C",
    body: "Cuerpo del paso C para el tutorial.",
    optional: true,
  },
];

function placeTarget(id: string) {
  const el = document.createElement("div");
  el.setAttribute("data-tour", id);
  el.textContent = id;
  el.getBoundingClientRect = () =>
    ({
      width: 120,
      height: 28,
      top: 60,
      left: 12,
      bottom: 88,
      right: 132,
      x: 12,
      y: 60,
      toJSON: () => ({}),
    }) as DOMRect;
  document.body.appendChild(el);
  return el;
}

const SESSION: Session = {
  token: "rag_sess_t",
  organizationId: "org-1",
  companyName: "Acme",
  email: "a@b.cl",
  roles: ["owner"],
};

afterEach(() => {
  document.querySelectorAll("[data-tour]").forEach((n) => n.remove());
});

describe("ProductTour", () => {
  it("no renderiza nada cuando está cerrado", () => {
    render(<ProductTour steps={STEPS} open={false} onSkip={() => {}} onComplete={() => {}} />);
    expect(screen.queryByRole("dialog")).toBeNull();
  });

  it("muestra título, cuerpo, contador y avanza con Siguiente", async () => {
    const user = userEvent.setup();
    placeTarget("tour-a");
    placeTarget("tour-b");
    placeTarget("tour-c");
    render(<ProductTour steps={STEPS} open onSkip={() => {}} onComplete={() => {}} />);
    expect(screen.getByRole("dialog", { name: "Paso A" })).toBeInTheDocument();
    expect(screen.getByText("1 / 3")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Atrás" })).toBeDisabled();
    await user.click(screen.getByRole("button", { name: "Siguiente" }));
    expect(screen.getByRole("dialog", { name: "Paso B" })).toBeInTheDocument();
    expect(screen.getByText("2 / 3")).toBeInTheDocument();
  });

  it("Atrás vuelve al paso anterior", async () => {
    const user = userEvent.setup();
    placeTarget("tour-a");
    placeTarget("tour-b");
    render(<ProductTour steps={STEPS} open onSkip={() => {}} onComplete={() => {}} />);
    await user.click(screen.getByRole("button", { name: "Siguiente" }));
    await user.click(screen.getByRole("button", { name: "Atrás" }));
    expect(screen.getByRole("dialog", { name: "Paso A" })).toBeInTheDocument();
  });

  it("Saltar llama onSkip", async () => {
    const user = userEvent.setup();
    const onSkip = vi.fn();
    placeTarget("tour-a");
    render(<ProductTour steps={STEPS} open onSkip={onSkip} onComplete={() => {}} />);
    await user.click(screen.getByRole("button", { name: "Saltar" }));
    expect(onSkip).toHaveBeenCalledTimes(1);
  });

  it("Escape llama onSkip", async () => {
    const user = userEvent.setup();
    const onSkip = vi.fn();
    placeTarget("tour-a");
    render(<ProductTour steps={STEPS} open onSkip={onSkip} onComplete={() => {}} />);
    await user.keyboard("{Escape}");
    expect(onSkip).toHaveBeenCalledTimes(1);
  });

  it("último paso muestra Listo y llama onComplete", async () => {
    const user = userEvent.setup();
    const onComplete = vi.fn();
    placeTarget("tour-a");
    placeTarget("tour-b");
    render(
      <ProductTour
        steps={STEPS.filter((s) => s.id !== "c")}
        open
        onSkip={() => {}}
        onComplete={onComplete}
      />
    );
    await user.click(screen.getByRole("button", { name: "Siguiente" }));
    expect(screen.getByRole("button", { name: "Listo" })).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Listo" }));
    expect(onComplete).toHaveBeenCalledTimes(1);
  });

  it("salta el paso opcional si el target no es visible", async () => {
    const user = userEvent.setup();
    const onComplete = vi.fn();
    placeTarget("tour-a");
    placeTarget("tour-b");
    render(<ProductTour steps={STEPS} open onSkip={() => {}} onComplete={onComplete} />);
    await user.click(screen.getByRole("button", { name: "Siguiente" }));
    await user.click(screen.getByRole("button", { name: "Listo" }));
    expect(onComplete).toHaveBeenCalledTimes(1);
  });

  it("sin violaciones de accesibilidad", async () => {
    placeTarget("tour-a");
    const { container } = render(
      <ProductTour steps={STEPS} open onSkip={() => {}} onComplete={() => {}} />
    );
    await expectAxeToHaveNoViolations(container);
  });
});

describe("ProductTourRoot", () => {
  it("auto-arranca si no hay persistencia", () => {
    for (const step of TOUR_STEPS) placeTarget(step.target);
    render(<ProductTourRoot session={SESSION} />);
    expect(screen.getByRole("dialog")).toBeInTheDocument();
  });

  it("no auto-arranca si ya se completó", () => {
    markCompleted();
    for (const step of TOUR_STEPS) placeTarget(step.target);
    render(<ProductTourRoot session={SESSION} />);
    expect(screen.queryByRole("dialog")).toBeNull();
  });

  it("no auto-arranca si blocked", () => {
    for (const step of TOUR_STEPS) placeTarget(step.target);
    render(<ProductTourRoot session={SESSION} blocked />);
    expect(screen.queryByRole("dialog")).toBeNull();
  });

  it("replay abre el tour aunque esté completed", async () => {
    markCompleted();
    for (const step of TOUR_STEPS) placeTarget(step.target);
    render(<ProductTourRoot session={SESSION} />);
    expect(screen.queryByRole("dialog")).toBeNull();
    requestProductTourStart();
    expect(await screen.findByRole("dialog")).toBeInTheDocument();
    expect(window.localStorage.getItem(PRODUCT_TOUR_STORAGE_KEY)).toContain("completed");
  });

  it("Saltar persiste skipped y cierra", async () => {
    const user = userEvent.setup();
    for (const step of TOUR_STEPS) placeTarget(step.target);
    render(<ProductTourRoot session={SESSION} />);
    await user.click(screen.getByRole("button", { name: "Saltar" }));
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(window.localStorage.getItem(PRODUCT_TOUR_STORAGE_KEY)).toContain("skipped");
  });
});
