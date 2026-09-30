import { afterEach, describe, expect, it, vi } from "vitest";
import {
  BLOOM_MS,
  DIVE_ANTICIPATION,
  DIVE_MS,
  DIVE_SCALE,
  ENTRY_EXPIRY_MS,
  armEntry,
  disarmEntry,
  entryArmed,
  subscribeEntry,
  type EntryTransit,
} from "./entryTransit";

afterEach(() => {
  disarmEntry();
  vi.useRealTimers();
});

describe("tránsito de entrada", () => {
  it("arma, avisa a los suscriptores y se limpia al desarmar", () => {
    const seen: EntryTransit[] = [];
    const unsubscribe = subscribeEntry((state) => seen.push(state));
    expect(seen).toHaveLength(1);
    expect(seen[0].armed).toBe(false);

    armEntry({ reduced: true });
    expect(seen.at(-1)).toMatchObject({ armed: true, reduced: true });
    expect(entryArmed()).toBe(true);

    disarmEntry();
    expect(seen.at(-1)?.armed).toBe(false);
    expect(entryArmed()).toBe(false);

    unsubscribe();
    armEntry();
    expect(seen.at(-1)?.armed).toBe(false);
  });

  it("deja de estar en curso cuando pasa la guarda de tiempo", () => {
    vi.useFakeTimers();
    armEntry();
    expect(entryArmed()).toBe(true);
    vi.advanceTimersByTime(ENTRY_EXPIRY_MS + 1);
    expect(entryArmed()).toBe(false);
  });
});

describe("tiempos de la travesía", () => {
  it("el bloom cabe dentro del zoom y la escala CSS no pixelea el bitmap", () => {
    expect(DIVE_MS).toBeGreaterThan(BLOOM_MS);
    expect(DIVE_ANTICIPATION).toBeGreaterThan(0);
    expect(DIVE_ANTICIPATION).toBeLessThan(1);
    expect(DIVE_SCALE).toBeGreaterThan(1);
    expect(DIVE_SCALE).toBeLessThanOrEqual(2);
  });
});
