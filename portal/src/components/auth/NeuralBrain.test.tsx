import { render, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { NeuralBrain, type NeuralStats } from "./NeuralBrain";

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

describe("NeuralBrain", () => {
  it("dibuja un frame estático y reporta métricas reales con reduced motion", async () => {
    mockReducedMotion(true);
    const raf = vi.spyOn(window, "requestAnimationFrame");
    const stats: NeuralStats[] = [];

    const { container } = render(<NeuralBrain onStats={(value) => stats.push(value)} />);

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

    const { unmount } = render(<NeuralBrain />);

    expect(raf).toHaveBeenCalled();
    unmount();
    expect(cancel).toHaveBeenCalled();
  });
});
