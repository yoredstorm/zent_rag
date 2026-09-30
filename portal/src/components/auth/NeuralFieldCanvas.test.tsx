import { render, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { NeuralFieldCanvas, type NeuralStats } from "./NeuralFieldCanvas";
import { emitNeuralEvent, onNeuralEvent, type NeuralEvent } from "./neuralSignal";
import { BLOOM_MS, DIVE_HOLD, DIVE_MS, DIVE_SCALE } from "./entryTransit";

function mockReducedMotion(reduce: boolean) {
  window.matchMedia = vi.fn().mockImplementation((query: string) => ({
    matches: reduce && query.includes("prefers-reduced-motion"),
    media: query,
    onchange: null,
    addListener: vi.fn(),
    removeListener: vi.fn(),
    addEventListener: vi.fn(),
    removeEventListener: vi.fn(),
    dispatchEvent: vi.fn(),
  }));
}

/** jsdom no implementa el contexto 2D: se sustituye por un doble inerte. */
function stubCanvasContext() {
  const gradient = { addColorStop: vi.fn() };
  const context = {
    canvas: null,
    globalAlpha: 1,
    globalCompositeOperation: "source-over",
    fillStyle: "",
    strokeStyle: "",
    lineWidth: 1,
    lineCap: "butt",
    lineJoin: "miter",
    setTransform: vi.fn(),
    translate: vi.fn(),
    rotate: vi.fn(),
    scale: vi.fn(),
    clearRect: vi.fn(),
    fillRect: vi.fn(),
    save: vi.fn(),
    restore: vi.fn(),
    beginPath: vi.fn(),
    closePath: vi.fn(),
    moveTo: vi.fn(),
    lineTo: vi.fn(),
    quadraticCurveTo: vi.fn(),
    stroke: vi.fn(),
    arc: vi.fn(),
    fill: vi.fn(),
    drawImage: vi.fn(),
    createRadialGradient: vi.fn(() => gradient),
    createLinearGradient: vi.fn(() => gradient),
  };
  vi.spyOn(HTMLCanvasElement.prototype, "getContext").mockReturnValue(
    context as unknown as CanvasRenderingContext2D
  );
}

let widthSpy: ReturnType<typeof vi.spyOn>;

beforeEach(() => {
  stubCanvasContext();
  widthSpy = vi.spyOn(window, "innerWidth", "get").mockReturnValue(1440);
});

afterEach(() => {
  widthSpy.mockRestore();
  vi.restoreAllMocks();
});

describe("NeuralFieldCanvas", () => {
  it("dibuja un frame estático y reporta métricas reales con reduced motion", async () => {
    mockReducedMotion(true);
    const raf = vi.spyOn(window, "requestAnimationFrame");
    const stats: NeuralStats[] = [];

    const { container } = render(<NeuralFieldCanvas onStats={(value) => stats.push(value)} />);

    const canvas = container.querySelector("canvas");
    expect(canvas).not.toBeNull();
    expect(canvas).toHaveAttribute("aria-hidden");
    await waitFor(() => expect(stats.length).toBeGreaterThan(0));
    expect(stats[0].neurons).toBeGreaterThan(0);
    expect(stats[0].synapses).toBeGreaterThan(stats[0].neurons);
    expect(stats[0].rate).toBeGreaterThan(0);
    expect(raf).not.toHaveBeenCalled();
  });

  it("anima con requestAnimationFrame cuando el movimiento está permitido", () => {
    mockReducedMotion(false);
    const raf = vi.spyOn(window, "requestAnimationFrame").mockReturnValue(1);
    const cancel = vi.spyOn(window, "cancelAnimationFrame").mockImplementation(() => {});

    const { unmount } = render(<NeuralFieldCanvas />);

    expect(raf).toHaveBeenCalled();
    unmount();
    expect(cancel).toHaveBeenCalled();
  });

  it("publica las métricas en el bus del acceso", async () => {
    mockReducedMotion(true);
    const events: NeuralEvent[] = [];
    const unsubscribe = onNeuralEvent((event) => events.push(event));

    render(<NeuralFieldCanvas />);

    await waitFor(() => expect(events.some((e) => e.type === "stats")).toBe(true));
    const statsEvent = events.find((e) => e.type === "stats");
    expect(statsEvent && statsEvent.type === "stats" && statsEvent.stats.neurons).toBeGreaterThan(0);
    unsubscribe();
  });

  it("congela el lienzo al dive y apunta el origen al nodo", async () => {
    mockReducedMotion(false);
    let next = 1;
    const raf = vi.spyOn(window, "requestAnimationFrame").mockImplementation(() => next++);
    const cancel = vi.spyOn(window, "cancelAnimationFrame").mockImplementation(() => {});

    const { container } = render(
      <div className="auth-net">
        <NeuralFieldCanvas />
      </div>
    );

    await waitFor(() => expect(raf).toHaveBeenCalled());
    const callsBefore = cancel.mock.calls.length;
    emitNeuralEvent({ type: "dive" });

    expect(cancel.mock.calls.length).toBeGreaterThan(callsBefore);
    const host = container.querySelector(".auth-net") as HTMLElement;
    expect(host.style.getPropertyValue("--dive-x")).toMatch(/%$/);
    expect(host.style.getPropertyValue("--dive-y")).toMatch(/%$/);
    expect(host.style.getPropertyValue("--auth-dive-ms")).toBe(`${DIVE_MS}ms`);
    expect(host.style.getPropertyValue("--auth-bloom-ms")).toBe(`${BLOOM_MS}ms`);
    expect(host.style.getPropertyValue("--auth-bloom-delay")).toBe(`${DIVE_MS - BLOOM_MS}ms`);
    expect(host.style.getPropertyValue("--auth-dive-scale")).toBe(String(DIVE_SCALE));
    expect(host.style.getPropertyValue("--auth-dive-hold")).toBe(String(DIVE_HOLD));
  });
});
