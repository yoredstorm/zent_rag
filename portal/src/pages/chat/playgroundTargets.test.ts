import { afterEach, describe, expect, it } from "vitest";
import {
  LAST_USED_KEY,
  conversationMatches,
  parsePlaygroundSearch,
  playgroundHref,
  readLastUsed,
  resolvePlaygroundTarget,
  sameTarget,
  writeLastUsed,
} from "./playgroundTargets";

const AGENTS = [
  { id: "a-off", name: "Borrador", is_active: false },
  { id: "a1", name: "Soporte", is_active: true },
];
const WORKFLOWS = [{ id: "w1", name: "Stock", status: "active" }];

afterEach(() => {
  window.localStorage.removeItem(LAST_USED_KEY);
});

describe("parsePlaygroundSearch", () => {
  it("lee target=agent&id", () => {
    expect(parsePlaygroundSearch(new URLSearchParams("target=agent&id=a1"))).toEqual({
      kind: "agent",
      id: "a1",
    });
  });

  it("lee conocimiento y workflow", () => {
    expect(parsePlaygroundSearch(new URLSearchParams("target=knowledge"))).toEqual({
      kind: "knowledge",
      id: "",
    });
    expect(parsePlaygroundSearch(new URLSearchParams("target=workflow&id=w1"))).toEqual({
      kind: "workflow",
      id: "w1",
    });
  });

  it("ignora query desconocida", () => {
    expect(parsePlaygroundSearch(new URLSearchParams("foo=1"))).toBeNull();
  });
});

describe("playgroundHref", () => {
  it("arma las tres formas de URL", () => {
    expect(playgroundHref({ kind: "knowledge", id: "" })).toBe("/chat?target=knowledge");
    expect(playgroundHref({ kind: "agent", id: "a1" })).toBe("/chat?target=agent&id=a1");
    expect(playgroundHref({ kind: "workflow", id: "" })).toBe("/chat?target=workflow");
  });
});

describe("resolvePlaygroundTarget", () => {
  it("respeta un agente de la URL si existe", () => {
    expect(
      resolvePlaygroundTarget({
        fromUrl: { kind: "agent", id: "a-off" },
        lastUsed: { kind: "knowledge", id: "" },
        agents: AGENTS,
        workflows: WORKFLOWS,
      }),
    ).toEqual({ kind: "agent", id: "a-off" });
  });

  it("sin id en URL agent elige el primer activo", () => {
    expect(
      resolvePlaygroundTarget({
        fromUrl: { kind: "agent", id: "" },
        lastUsed: null,
        agents: AGENTS,
        workflows: WORKFLOWS,
      }),
    ).toEqual({ kind: "agent", id: "a1" });
  });

  it("sin URL usa el último destino válido", () => {
    expect(
      resolvePlaygroundTarget({
        fromUrl: null,
        lastUsed: { kind: "workflow", id: "w1" },
        agents: AGENTS,
        workflows: WORKFLOWS,
      }),
    ).toEqual({ kind: "workflow", id: "w1" });
  });

  it("sin URL ni last-used elige el primer agente activo", () => {
    expect(
      resolvePlaygroundTarget({
        fromUrl: null,
        lastUsed: null,
        agents: AGENTS,
        workflows: [],
      }),
    ).toEqual({ kind: "agent", id: "a1" });
  });

  it("cae a conocimiento si no hay agentes", () => {
    expect(
      resolvePlaygroundTarget({
        fromUrl: null,
        lastUsed: { kind: "agent", id: "desaparecido" },
        agents: [],
        workflows: [],
      }),
    ).toEqual({ kind: "knowledge", id: "" });
  });

  it("target=knowledge gana aunque haya agentes", () => {
    expect(
      resolvePlaygroundTarget({
        fromUrl: { kind: "knowledge", id: "" },
        lastUsed: { kind: "agent", id: "a1" },
        agents: AGENTS,
        workflows: WORKFLOWS,
      }),
    ).toEqual({ kind: "knowledge", id: "" });
  });
});

describe("conversationMatches", () => {
  it("trata las conversaciones viejas como conocimiento", () => {
    expect(conversationMatches({}, { kind: "knowledge", id: "" })).toBe(true);
    expect(conversationMatches({}, { kind: "agent", id: "a1" })).toBe(false);
  });

  it("filtra por agente", () => {
    expect(conversationMatches({ target: "agent", targetId: "a1" }, { kind: "agent", id: "a1" })).toBe(true);
    expect(conversationMatches({ target: "agent", targetId: "a2" }, { kind: "agent", id: "a1" })).toBe(false);
  });
});

describe("last-used", () => {
  it("persiste y lee", () => {
    writeLastUsed({ kind: "agent", id: "a1" });
    expect(readLastUsed()).toEqual({ kind: "agent", id: "a1" });
  });
});

describe("sameTarget", () => {
  it("compara kind+id", () => {
    expect(sameTarget({ kind: "agent", id: "a1" }, { kind: "agent", id: "a1" })).toBe(true);
    expect(sameTarget({ kind: "agent", id: "a1" }, { kind: "agent", id: "a2" })).toBe(false);
  });
});
