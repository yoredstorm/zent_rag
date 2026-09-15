export type PlaygroundTargetKind = "agent" | "workflow" | "knowledge";

export type PlaygroundTarget = {
  kind: PlaygroundTargetKind;
  /** Vacío en conocimiento. UUID del agente o flujo en los otros modos. */
  id: string;
};

export type PlaygroundAgent = {
  id: string;
  name: string;
  is_active: boolean;
  description?: string | null;
  config?: { purpose?: string | null; source_ids?: string[] };
};

export type PlaygroundWorkflow = {
  id: string;
  name: string;
  status: string;
};

export const LAST_USED_KEY = "zent_playground_target_v1";

export function parsePlaygroundSearch(search: URLSearchParams): PlaygroundTarget | null {
  const raw = search.get("target");
  if (raw === "knowledge") return { kind: "knowledge", id: "" };
  if (raw === "agent" || raw === "workflow") {
    return { kind: raw, id: (search.get("id") || "").trim() };
  }
  return null;
}

export function playgroundHref(target: PlaygroundTarget): string {
  if (target.kind === "knowledge") return "/chat?target=knowledge";
  const id = encodeURIComponent(target.id);
  return target.id ? `/chat?target=${target.kind}&id=${id}` : `/chat?target=${target.kind}`;
}

export function playgroundSearchParams(target: PlaygroundTarget): URLSearchParams {
  const params = new URLSearchParams();
  params.set("target", target.kind);
  if (target.kind !== "knowledge" && target.id) params.set("id", target.id);
  return params;
}

export function sameTarget(a: PlaygroundTarget, b: PlaygroundTarget): boolean {
  return a.kind === b.kind && a.id === b.id;
}

export function readLastUsed(): PlaygroundTarget | null {
  try {
    const raw = window.localStorage.getItem(LAST_USED_KEY);
    if (!raw) return null;
    const parsed = JSON.parse(raw) as { kind?: string; id?: string };
    if (parsed.kind === "knowledge") return { kind: "knowledge", id: "" };
    if (parsed.kind === "agent" || parsed.kind === "workflow") {
      return { kind: parsed.kind, id: String(parsed.id || "") };
    }
    return null;
  } catch {
    return null;
  }
}

export function writeLastUsed(target: PlaygroundTarget): void {
  try {
    window.localStorage.setItem(LAST_USED_KEY, JSON.stringify(target));
  } catch {
    // storage lleno: el destino sigue en la URL
  }
}

function firstAgent(agents: PlaygroundAgent[]): PlaygroundAgent | undefined {
  return agents.find((a) => a.is_active) ?? agents[0];
}

function idExists(kind: PlaygroundTargetKind, id: string, agents: PlaygroundAgent[], workflows: PlaygroundWorkflow[]): boolean {
  if (!id) return false;
  if (kind === "agent") return agents.some((a) => a.id === id);
  if (kind === "workflow") return workflows.some((w) => w.id === id);
  return true;
}

/**
 * Prioridad: URL válida > último usado válido > primer agente activo > conocimiento.
 * Un `target=agent` sin id (o con id inexistente) cae al primer agente; si no hay
 * catálogo, deja el id vacío para que la barra muestre el CTA de crear.
 */
export function resolvePlaygroundTarget(input: {
  fromUrl: PlaygroundTarget | null;
  lastUsed: PlaygroundTarget | null;
  agents: PlaygroundAgent[];
  workflows: PlaygroundWorkflow[];
}): PlaygroundTarget {
  const { fromUrl, lastUsed, agents, workflows } = input;

  if (fromUrl?.kind === "knowledge") return { kind: "knowledge", id: "" };

  if (fromUrl?.kind === "agent") {
    if (idExists("agent", fromUrl.id, agents, workflows)) return fromUrl;
    const pick = firstAgent(agents);
    return { kind: "agent", id: pick?.id ?? fromUrl.id };
  }

  if (fromUrl?.kind === "workflow") {
    if (idExists("workflow", fromUrl.id, agents, workflows)) return fromUrl;
    return { kind: "workflow", id: workflows[0]?.id ?? fromUrl.id };
  }

  if (lastUsed?.kind === "knowledge") return { kind: "knowledge", id: "" };
  if (lastUsed && idExists(lastUsed.kind, lastUsed.id, agents, workflows)) return lastUsed;

  const pick = firstAgent(agents);
  if (pick) return { kind: "agent", id: pick.id };
  return { kind: "knowledge", id: "" };
}

/** Conversaciones viejas (sin target) pertenecen a conocimiento. */
export function conversationMatches(
  conversation: { target?: string; targetId?: string },
  target: PlaygroundTarget,
): boolean {
  const kind = conversation.target || "knowledge";
  const id = conversation.targetId || "";
  if (target.kind === "knowledge") return kind === "knowledge";
  return kind === target.kind && id === target.id;
}
