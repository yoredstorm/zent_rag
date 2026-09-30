import { afterEach, describe, expect, it } from "vitest";
import { DIVE_PREF_KEY, diveEffectOn, diveQuiet, setDiveEffect } from "./divePref";

afterEach(() => {
  localStorage.removeItem(DIVE_PREF_KEY);
  setDiveEffect(true);
});

describe("preferencia del dive", () => {
  it("por defecto el efecto está encendido", () => {
    expect(diveEffectOn()).toBe(true);
    expect(diveQuiet(false)).toBe(false);
  });

  it("apagado queda en localStorage y se lee como quiet", () => {
    setDiveEffect(false);
    expect(localStorage.getItem(DIVE_PREF_KEY)).toBe("off");
    expect(diveEffectOn()).toBe(false);
    expect(diveQuiet(false)).toBe(true);
  });

  it("el movimiento reducido del sistema manda aunque el efecto esté on", () => {
    setDiveEffect(true);
    expect(diveQuiet(true)).toBe(true);
  });
});
