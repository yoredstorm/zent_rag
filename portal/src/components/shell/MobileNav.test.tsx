import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useCallback, useRef, useState } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { Session } from "../../api";
import { TOUR_STEPS } from "../../lib/productTour";
import { ProductTourRoot } from "../ProductTour";
import { MobileNav } from "./MobileNav";

// El sidebar real pide AuthProvider + entitlements: acá sólo importa que el
// drawer sea un dialog de Radix con un target del tutorial adentro.
vi.mock("./AppSidebar", () => ({
  AppSidebar: () => <nav data-tour="nav-dashboard">Panel general</nav>,
}));

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

/** Mismo cableado que App: el tutorial abre el drawer y manda sobre él. */
function Shell() {
  const [navOpen, setNavOpen] = useState(false);
  const [tourActive, setTourActive] = useState(false);
  const tourOwnsNav = useRef(false);
  const onTourActive = useCallback((active: boolean) => {
    setTourActive(active);
    if (active) {
      if (window.matchMedia("(min-width: 1024px)").matches) return;
      tourOwnsNav.current = true;
      setNavOpen(true);
      return;
    }
    if (!tourOwnsNav.current) return;
    tourOwnsNav.current = false;
    setNavOpen(false);
  }, []);

  return (
    <>
      <ProductTourRoot session={SESSION} onTourActive={onTourActive} />
      <MobileNav
        open={navOpen}
        onOpenChange={setNavOpen}
        interactionLocked={tourActive}
      />
    </>
  );
}

describe("MobileNav + tutorial", () => {
  it("el tutorial avanza y salta con el menú móvil abierto", async () => {
    const user = userEvent.setup();
    for (const step of TOUR_STEPS) {
      const el = document.createElement("div");
      el.setAttribute("data-tour", step.target);
      document.body.appendChild(el);
    }
    render(<Shell />);

    // El drawer se abre para señalar el menú: el tutorial queda por encima y
    // sigue siendo operable (antes el body quedaba con pointer-events: none y
    // el tutorial salía del árbol de accesibilidad).
    expect(await screen.findByRole("dialog", { name: "Panel general" })).toBeInTheDocument();
    expect(screen.getByRole("dialog", { name: "Menú de navegación" })).toBeInTheDocument();
    expect(document.body.style.pointerEvents).not.toBe("none");

    await user.click(screen.getByRole("button", { name: "Siguiente" }));
    expect(screen.getByRole("dialog", { name: "Construir" })).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Saltar" }));
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(document.body.style.pointerEvents).toBe("");
  });

  it("el drawer sigue siendo modal cuando el tutorial no manda", async () => {
    render(<MobileNav open onOpenChange={() => {}} />);
    expect(screen.getByRole("dialog", { name: "Menú de navegación" })).toBeInTheDocument();
    expect(document.body.style.pointerEvents).toBe("none");
  });

  it("con la interacción tomada, un tap afuera no cierra el drawer", async () => {
    const user = userEvent.setup();
    const onOpenChange = vi.fn();
    render(<MobileNav open onOpenChange={onOpenChange} interactionLocked />);

    await user.click(document.body);
    expect(onOpenChange).not.toHaveBeenCalled();
    expect(screen.getByRole("dialog", { name: "Menú de navegación" })).toBeInTheDocument();
  });
});
