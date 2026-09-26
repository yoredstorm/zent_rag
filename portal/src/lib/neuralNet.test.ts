import { describe, expect, it } from "vitest";
import {
  MAX_PULSE_RATIO,
  activePulses,
  assignZones,
  createNeuralNet,
  excitePointer,
  fire,
  netStats,
  setFocus,
  stepNeuralNet,
  triggerError,
  triggerSubmit,
  triggerSuccess,
} from "./neuralNet";

function warm(seed = 7, width = 1280, height = 800, steps = 240) {
  const net = createNeuralNet({ width, height, seed });
  for (let i = 0; i < steps; i += 1) stepNeuralNet(net, 1 / 60);
  return net;
}

describe("red neuronal espacial", () => {
  it("es determinista por seed", () => {
    const a = createNeuralNet({ width: 1200, height: 800, seed: 7 });
    const b = createNeuralNet({ width: 1200, height: 800, seed: 7 });
    const c = createNeuralNet({ width: 1200, height: 800, seed: 8 });

    expect(a.nodes.map((n) => [n.x, n.y, n.z])).toEqual(b.nodes.map((n) => [n.x, n.y, n.z]));
    expect(a.edges.length).toBe(b.edges.length);
    expect(a.nodes.map((n) => n.x)).not.toEqual(c.nodes.map((n) => n.x));
  });

  it("respeta el viewport y reparte los tres planos", () => {
    const net = createNeuralNet({ width: 1440, height: 900, seed: 21 });
    expect(net.nodes.length).toBeGreaterThan(60);
    for (const node of net.nodes) {
      expect(node.x).toBeGreaterThanOrEqual(0);
      expect(node.x).toBeLessThanOrEqual(1440);
      expect(node.y).toBeGreaterThanOrEqual(0);
      expect(node.y).toBeLessThanOrEqual(900);
      expect(node.z).toBeGreaterThanOrEqual(0);
      expect(node.z).toBeLessThanOrEqual(1);
      expect([0, 1, 2]).toContain(node.plane);
    }
    const planes = new Set(net.nodes.map((n) => n.plane));
    expect(planes.size).toBe(3);
  });

  it("conecta enlaces válidos, sin duplicados y más enlaces que nodos", () => {
    const net = createNeuralNet({ width: 1024, height: 768, seed: 3 });
    const seen = new Set<string>();
    for (const edge of net.edges) {
      expect(edge.a).not.toBe(edge.b);
      expect(net.nodes[edge.a]).toBeDefined();
      expect(net.nodes[edge.b]).toBeDefined();
      const key = `${Math.min(edge.a, edge.b)}:${Math.max(edge.a, edge.b)}`;
      expect(seen.has(key)).toBe(false);
      seen.add(key);
      expect(edge.length).toBeGreaterThan(0);
    }
    expect(net.edges.length).toBeGreaterThan(net.nodes.length);
  });

  it("propaga señal y mide la tasa real", () => {
    const net = warm(11);
    expect(net.rate).toBeGreaterThan(0);
    expect(activePulses(net)).toBeGreaterThan(0);
  });

  it("no se satura: los pulsos quedan acotados", () => {
    const net = createNeuralNet({ width: 1440, height: 900, seed: 5 });
    for (let i = 0; i < 900; i += 1) stepNeuralNet(net, 1 / 60);
    expect(net.pulses.length).toBeLessThanOrEqual(
      Math.max(30, Math.round(net.nodes.length * MAX_PULSE_RATIO)) + 8
    );
    expect(net.firings.length).toBeLessThan(400);
  });

  it("respeta el refractario de cada nodo", () => {
    const net = createNeuralNet({ width: 1200, height: 800, seed: 13 });
    expect(fire(net, 0)).toBe(true);
    expect(fire(net, 0)).toBe(false);
    stepNeuralNet(net, 1 / 30);
    expect(fire(net, 0)).toBe(false);
    stepNeuralNet(net, 1 / 30);
    stepNeuralNet(net, 1 / 30);
    expect(fire(net, 0)).toBe(true);
  });

  it("el puntero empuja y excita la zona que toca", () => {
    const net = createNeuralNet({ width: 1280, height: 800, seed: 31 });
    const node = net.nodes[10];
    node.refractory = 0;
    const fired = excitePointer(net, node.x + 4, node.y + 4, 1);
    expect(fired).toBeGreaterThan(0);
    expect(Math.abs(node.dvx) + Math.abs(node.dvy)).toBeGreaterThan(0);
    stepNeuralNet(net, 1 / 60);
    expect(Math.abs(node.vx) + Math.abs(node.vy)).toBeGreaterThan(0);
    expect(node.energy).toBeGreaterThan(0);
  });

  it("el foco enciende una ruta concreta", () => {
    const net = createNeuralNet({ width: 1440, height: 900, seed: 17 });
    assignZones(net, { compact: false });
    const members = net.nodes.filter((n) => n.zone === "email");
    expect(members.length).toBeGreaterThan(0);

    setFocus(net, "email");
    expect(net.focus.email).toBe(1);
    expect(net.focusZone).toBe("email");
    expect(members.some((n) => n.energy > 0)).toBe(true);
    expect(net.pulses.length).toBeGreaterThan(0);

    setFocus(net, null);
    expect(net.focusZone).toBeNull();
  });

  it("el envío lanza una onda y sube la presión", () => {
    const net = createNeuralNet({ width: 1440, height: 900, seed: 41 });
    triggerSubmit(net);
    expect(net.submit).toBeGreaterThan(0.9);
    expect(net.wave).not.toBeNull();
    expect(net.wave?.tone).toBe("signal");
    const before = net.rate;
    for (let i = 0; i < 120; i += 1) stepNeuralNet(net, 1 / 60);
    expect(net.rate).toBeGreaterThan(before);
  });

  it("el error contrae la red y el éxito la enciende", () => {
    const net = createNeuralNet({ width: 1280, height: 800, seed: 43 });
    triggerError(net);
    expect(net.recoil).toBeGreaterThan(0.9);
    expect(net.submit).toBe(0);

    triggerSuccess(net);
    expect(net.success).toBeGreaterThan(0.9);
    expect(net.recoil).toBe(0);
    expect(net.pulses.length).toBeGreaterThan(0);
  });

  it("decae la energía cuando no hay señal", () => {
    const net = createNeuralNet({ width: 1280, height: 800, seed: 19 });
    fire(net, 0, 1.2);
    const peak = net.nodes[0].energy;
    for (let i = 0; i < 120; i += 1) stepNeuralNet(net, 1 / 60);
    expect(net.nodes[0].energy).toBeLessThan(peak);
  });

  it("las métricas describen la red", () => {
    const net = warm(23, 1024, 768, 120);
    const stats = netStats(net);
    expect(stats.neurons).toBe(net.nodes.length);
    expect(stats.synapses).toBe(net.edges.length);
    expect(stats.active).toBe(net.pulses.length);
    expect(stats.synapses).toBeGreaterThan(stats.neurons);
  });
});
