import { afterEach, describe, expect, it, vi } from "vitest";
import {
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
