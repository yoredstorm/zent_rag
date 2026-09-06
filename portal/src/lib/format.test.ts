import { describe, expect, it } from "vitest";
import { fmtCurrency, fmtCurrencyCents, fmtDate, fmtDateTime, fmtLatency, fmtNum, timeAgo } from "./format";

describe("fmtNum", () => {
  it("formatea números con el locale canónico", () => {
    expect(fmtNum(1234)).toBe("1,234");
    expect(fmtNum(0)).toBe("0");
  });
  it("devuelve — para nulos/NaN", () => {
    expect(fmtNum(null)).toBe("—");
    expect(fmtNum(undefined)).toBe("—");
    expect(fmtNum(Number.NaN)).toBe("—");
  });
});

describe("fmtDate / fmtDateTime", () => {
  it("formatea ISO con el locale es-PE", () => {
    const d = new Date(2026, 0, 5, 9, 30).toISOString();
    expect(fmtDate(d)).toMatch(/ene/i);
    expect(fmtDateTime(d)).toContain("09");
  });
  it("devuelve — para entradas inválidas", () => {
    expect(fmtDate(null)).toBe("—");
    expect(fmtDate("no-es-fecha")).toBe("—");
  });
});

describe("fmtCurrency / fmtCurrencyCents", () => {
  it("formatea USD con el locale es-PE", () => {
    expect(fmtCurrency(12.5)).toContain("USD");
    expect(fmtCurrency(12.5)).toContain("12.50");
    expect(fmtCurrency(0)).toContain("0.00");
  });
  it("convierte centavos a moneda", () => {
    expect(fmtCurrencyCents(1250, 2)).toContain("12.50");
  });
  it("devuelve — para nulos", () => {
    expect(fmtCurrency(null)).toBe("—");
    expect(fmtCurrencyCents(undefined)).toBe("—");
  });
});

describe("fmtLatency", () => {
  it("usa ms bajo 1s y segundos sobre 1s", () => {
    expect(fmtLatency(500)).toBe("500 ms");
    expect(fmtLatency(1500)).toBe("1.5 s");
  });
  it("devuelve — para nulos", () => {
    expect(fmtLatency(null)).toBe("—");
  });
});

describe("timeAgo", () => {
  it("devuelve hace X min/h/d según la antigüedad", () => {
    const now = Date.now();
    expect(timeAgo(new Date(now - 30_000).toISOString())).toMatch(/hace \d+s/);
    expect(timeAgo(new Date(now - 120_000).toISOString())).toMatch(/hace \d+ min/);
    expect(timeAgo(new Date(now - 3_600_000 * 2).toISOString())).toMatch(/hace \d+ h/);
    expect(timeAgo(new Date(now - 86_400_000 * 3).toISOString())).toMatch(/hace \d+ d/);
  });
  it("devuelve — para entradas inválidas", () => {
    expect(timeAgo(null)).toBe("—");
    expect(timeAgo("basura")).toBe("—");
  });
});