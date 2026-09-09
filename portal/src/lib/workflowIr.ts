import { blockDef, defaultFields, type BlockKind } from "./workflowBlocks";

export type WorkflowStep = {
  type: string;
  config: Record<string, unknown>;
  then?: WorkflowStep[];
  else?: WorkflowStep[];
};

export type BlockNode = {
  id: string;
  kind: BlockKind;
  fields: Record<string, string>;
  next?: BlockNode;
  then?: BlockNode;
  else?: BlockNode;
};

export type WorkflowIr = {
  trigger_type: "webhook" | "schedule" | "event";
  trigger_config: Record<string, unknown>;
  steps: WorkflowStep[];
  editor_state: { blocks: BlockNode };
};

let _seq = 0;
export function newBlockId(): string {
  _seq += 1;
  return `b${_seq}`;
}

export function makeBlock(kind: BlockKind, fields?: Record<string, string>): BlockNode {
  return { id: newBlockId(), kind, fields: { ...defaultFields(kind), ...(fields || {}) } };
}

export function chainToArray(node: BlockNode | undefined): WorkflowStep[] {
  const out: WorkflowStep[] = [];
  let cur: BlockNode | undefined = node;
  while (cur) {
    const def = blockDef(cur.kind);
    if (!def.hat && def.stepType) {
      const step: WorkflowStep = {
        type: def.stepType,
        config: { ...cur.fields },
      };
      if (def.hasThenElse) {
        step.then = chainToArray(cur.then);
        step.else = chainToArray(cur.else);
      }
      out.push(step);
    }
    cur = cur.next;
  }
  return out;
}

export function arrayToChain(steps: WorkflowStep[] | undefined): BlockNode | undefined {
  let head: BlockNode | undefined;
  let prev: BlockNode | undefined;
  for (const step of steps || []) {
    const kind = kindForStep(step);
    if (!kind) continue;
    const node = makeBlock(kind, stringifyFields(step.config));
    if (blockDef(kind).hasThenElse) {
      node.then = arrayToChain(step.then);
      node.else = arrayToChain(step.else);
    }
    if (!head) head = node;
    if (prev) prev.next = node;
    prev = node;
  }
  return head;
}

function kindForStep(step: WorkflowStep): BlockKind | null {
  if (step.type === "api_call") return "api_call";
  if (step.type === "kb_query") return "kb_query";
  if (step.type === "llm") return "llm";
  if (step.type === "condition") return "condition";
  if (step.type === "notify") return "notify";
  return null;
}

function stringifyFields(config: Record<string, unknown> | undefined): Record<string, string> {
  const out: Record<string, string> = {};
  for (const [k, v] of Object.entries(config || {})) {
    if (v == null) continue;
    out[k] = typeof v === "string" ? v : JSON.stringify(v);
  }
  return out;
}

export function blocksToIr(root: BlockNode | null): WorkflowIr {
  const hat = root && blockDef(root.kind).hat ? root : makeBlock("hat_webhook");
  const trigger_type =
    hat.kind === "hat_schedule" ? "schedule" : hat.kind === "hat_event" ? "event" : "webhook";
  const trigger_config: Record<string, unknown> = {};
  if (trigger_type === "schedule") {
    const n = parseInt(hat.fields.every_minutes || "5", 10);
    trigger_config.every_minutes = Number.isFinite(n) ? Math.min(Math.max(n, 1), 1440) : 5;
  }
  return {
    trigger_type,
    trigger_config,
    steps: chainToArray(hat.next),
    editor_state: { blocks: hat },
  };
}

export function irToBlocks(
  triggerType: string,
  triggerConfig: Record<string, unknown> | undefined,
  steps: WorkflowStep[] | undefined,
  editorState?: { blocks?: BlockNode }
): BlockNode {
  if (editorState?.blocks?.kind) return editorState.blocks;
  const hatKind: BlockKind =
    triggerType === "schedule" ? "hat_schedule" : triggerType === "event" ? "hat_event" : "hat_webhook";
  const hat = makeBlock(hatKind);
  if (hatKind === "hat_schedule") {
    hat.fields.every_minutes = String(triggerConfig?.every_minutes ?? 5);
  }
  hat.next = arrayToChain(steps);
  return hat;
}

export function reporterHints(root: BlockNode | null): string[] {
  const hints = ["trigger.*"];
  const steps = root ? chainToArray(root.next) : [];
  steps.forEach((s, i) => {
    if (s.type === "api_call") hints.push(`steps.${i}.output.extracted`);
    if (s.type === "kb_query") hints.push(`steps.${i}.output.chunks`);
    if (s.type === "llm") hints.push(`steps.${i}.output.text`);
  });
  return hints;
}
