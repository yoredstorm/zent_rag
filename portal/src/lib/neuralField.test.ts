import { describe, expect, it } from "vitest";
import {
  MAX_PULSES_PER_NEURON,
  activePulses,
  brainField,
  createNeuralField,
  excite,
  fire,
  stepNeuralField,
} from "./neuralField";

describe("campo neuronal", () => {
  it("es determinista por seed", () => {
    const a = createNeuralField({ seed: 7, count: 80 });
    const b = createNeuralField({ seed: 7, count: 80 });
    const c = createNeuralField({ seed: 8, count: 80 });

    expect(a.neurons.map((n) => [n.x, n.y])).toEqual(b.neurons.map((n) => [n.x, n.y]));
    expect(a.synapses.length).toBe(b.synapses.length);
    expect(a.neurons.map((n) => n.x)).not.toEqual(c.neurons.map((n) => n.x));
  });

  it("coloca todas las neuronas dentro de la silueta del cerebro", () => {
    const field = createNeuralField({ seed: 21, count: 200 });
    expect(field.neurons.length).toBeGreaterThan(100);
    for (const neuron of field.neurons) {
      expect(brainField(neuron.x, neuron.y)).toBeGreaterThan(0);
      expect(neuron.x).toBeGreaterThan(0);
      expect(neuron.x).toBeLessThan(1);
      expect(neuron.depth).toBeGreaterThanOrEqual(0);
      expect(neuron.depth).toBeLessThanOrEqual(1);
    }
  });

  it("conecta sinapsis válidas y sin duplicados", () => {
    const field = createNeuralField({ seed: 3, count: 120 });
    const seen = new Set<string>();
    for (const synapse of field.synapses) {
      expect(synapse.a).not.toBe(synapse.b);
      expect(field.neurons[synapse.a]).toBeDefined();
      expect(field.neurons[synapse.b]).toBeDefined();
      const key = `${Math.min(synapse.a, synapse.b)}:${Math.max(synapse.a, synapse.b)}`;
      expect(seen.has(key)).toBe(false);
      seen.add(key);
    }
    // Red conectada de verdad: más de una sinapsis por neurona en promedio.
    expect(field.synapses.length).toBeGreaterThan(field.neurons.length);
  });

  it("propaga señal: los pulsos disparan y la tasa se mide", () => {
    const field = createNeuralField({ seed: 11, count: 140 });
    for (let i = 0; i < 180; i += 1) stepNeuralField(field, 1 / 60);
    expect(field.rate).toBeGreaterThan(0);
    expect(activePulses(field)).toBeGreaterThan(0);
  });

  it("no se satura: los pulsos quedan acotados", () => {
    const field = createNeuralField({ seed: 5, count: 160 });
    for (let i = 0; i < 900; i += 1) stepNeuralField(field, 1 / 60);
    expect(field.pulses.length).toBeLessThanOrEqual(
      field.neurons.length * MAX_PULSES_PER_NEURON + 8
    );
    expect(field.firings.length).toBeLessThan(400);
  });

  it("respeta el refractario de cada neurona", () => {
    const field = createNeuralField({ seed: 13, count: 90 });
    const index = 0;
    expect(fire(field, index)).toBe(true);
    expect(fire(field, index)).toBe(false);
    // El paso se acota a 50 ms por frame: hacen falta dos para salir del refractario.
    stepNeuralField(field, 0.05);
    expect(fire(field, index)).toBe(false);
    stepNeuralField(field, 0.05);
    expect(fire(field, index)).toBe(true);
  });

  it("el puntero excita la zona que toca", () => {
    const field = createNeuralField({ seed: 31, count: 120 });
    const target = field.neurons[10];
    target.refractory = 0;
    const fired = excite(field, target.x, target.y, 0.05);
    expect(fired).toBeGreaterThan(0);
    expect(field.neurons[10].energy).toBeGreaterThan(0);
  });

  it("decae la energía cuando no hay señal", () => {
    const field = createNeuralField({ seed: 17, count: 60 });
    const neuron = field.neurons[0];
    fire(field, 0, 1);
    const peak = neuron.energy;
    for (let i = 0; i < 120; i += 1) stepNeuralField(field, 1 / 60);
    expect(neuron.energy).toBeLessThan(peak);
  });
});
