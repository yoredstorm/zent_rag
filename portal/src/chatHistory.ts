export type StoredMessage = {
  role: "user" | "assistant";
  content: string;
  sources?: { text: string; image?: string; score?: number }[];
  sqlQuery?: string | null;
  method?: string;
  lazyIngested?: boolean;
  queryId?: string;
  userQuery?: string;
  rated?: "up" | "down";
  latencyMs?: number;
  stopped?: boolean;
};

export type Conversation = {
  id: string;
  title: string;
  updatedAt: number;
  messages: StoredMessage[];
};

const KEY_PREFIX = "rag_chat_conv_";

function storageKey(tenantId: string) {
  return `${KEY_PREFIX}${tenantId}`;
}

export function listConversations(tenantId: string): Conversation[] {
  try {
    const raw = localStorage.getItem(storageKey(tenantId));
    if (!raw) return [];
    const parsed = JSON.parse(raw) as Conversation[];
    return Array.isArray(parsed) ? parsed : [];
  } catch {
    return [];
  }
}

function persist(tenantId: string, conversations: Conversation[]) {
  try {
    localStorage.setItem(storageKey(tenantId), JSON.stringify(conversations));
  } catch {
    // storage lleno o no disponible: la conversación sigue en memoria
  }
}

export function loadConversation(tenantId: string, id: string): Conversation | null {
  return listConversations(tenantId).find((c) => c.id === id) ?? null;
}

export function upsertConversation(tenantId: string, conversation: Conversation) {
  const all = listConversations(tenantId).filter((c) => c.id !== conversation.id);
  const next = [
    { ...conversation, updatedAt: Date.now() },
    ...all,
  ].sort((a, b) => b.updatedAt - a.updatedAt);
  persist(tenantId, next);
  return next;
}

export function deleteConversation(tenantId: string, id: string): Conversation[] {
  const next = listConversations(tenantId).filter((c) => c.id !== id);
  persist(tenantId, next);
  return next;
}

export function renameConversation(
  tenantId: string,
  id: string,
  title: string
): Conversation[] {
  const next = listConversations(tenantId).map((c) =>
    c.id === id ? { ...c, title } : c
  );
  persist(tenantId, next);
  return next;
}

export function newConversationId(): string {
  if (typeof crypto !== "undefined" && "randomUUID" in crypto) {
    return crypto.randomUUID();
  }
  return `conv-${Date.now()}-${Math.random().toString(36).slice(2, 10)}`;
}

export function groupByDay(conversations: Conversation[]): { label: string; items: Conversation[] }[] {
  const groups = new Map<string, Conversation[]>();
  for (const c of conversations) {
    const d = new Date(c.updatedAt);
    const today = new Date();
    const yesterday = new Date();
    yesterday.setDate(today.getDate() - 1);
    let label: string;
    if (d.toDateString() === today.toDateString()) label = "Hoy";
    else if (d.toDateString() === yesterday.toDateString()) label = "Ayer";
    else label = d.toLocaleDateString("es-PE", { day: "2-digit", month: "short" });
    const arr = groups.get(label) ?? [];
    arr.push(c);
    groups.set(label, arr);
  }
  return Array.from(groups.entries()).map(([label, items]) => ({ label, items }));
}
