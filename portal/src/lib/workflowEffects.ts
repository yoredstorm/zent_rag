import { EXTERNAL_EFFECT_NODE_TYPES } from "./workflowGraph";

export type PlannedEffect = {
  node_id: string;
  node_type: string;
  planned: Record<string, unknown>;
};

export type EffectVerificationItem = {
  node_id: string;
  node_type?: string;
  label?: string;
  kind?: string;
};

export type EffectVerificationLevel = "NONE" | "SIMULATED" | "DECLARED" | "UNVERIFIED";

export type EffectVerification = {
  level: EffectVerificationLevel;
  unverified: EffectVerificationItem[];
  declared: EffectVerificationItem[];
  simulated: EffectVerificationItem[];
};

const EXTERNAL = new Set<string>(EXTERNAL_EFFECT_NODE_TYPES);

function isPinned(planned: Record<string, unknown>): boolean {
  return planned.pinned === true || planned.pinned_failure === true;
}

export function classifyPlannedEffects(effects?: PlannedEffect[]): EffectVerification {
  const unverified: EffectVerificationItem[] = [];
  const declared: EffectVerificationItem[] = [];
  const simulated: EffectVerificationItem[] = [];

  for (const effect of effects ?? []) {
    const item: EffectVerificationItem = {
      node_id: effect.node_id,
      node_type: effect.node_type,
      label: effect.node_id,
      kind: typeof effect.planned?.kind === "string" ? effect.planned.kind : "",
    };
    if (isPinned(effect.planned ?? {})) {
      declared.push(item);
    } else if (EXTERNAL.has(effect.node_type)) {
      unverified.push(item);
    } else {
      simulated.push(item);
    }
  }

  let level: EffectVerificationLevel = "NONE";
  if (unverified.length > 0) level = "UNVERIFIED";
  else if (declared.length > 0) level = "DECLARED";
  else if (simulated.length > 0) level = "SIMULATED";

  return { level, unverified, declared, simulated };
}

export function effectLabel(item: EffectVerificationItem): string {
  return item.label || item.node_type || item.node_id;
}
