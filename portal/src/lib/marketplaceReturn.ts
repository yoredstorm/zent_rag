/** Vuelta al diseño. Solo rutas internas de ZENT. Rechaza open redirects. */

const SAFE_PATH = /^\/(?!\/)[A-Za-z0-9/_\-?=&%.]*$/;
const SAFE_PREFIXES = ["/workflows", "/marketplace", "/agents", "/roles"];
const SAFE_ID = /^[A-Za-z0-9_-]{1,80}$/;
const SAFE_CAPABILITY = /^[A-Za-z0-9._:-]{1,120}$/;

export function safeReturnTo(value: string | null | undefined): string | null {
  if (!value) return null;
  const text = value.trim();
  if (!SAFE_PATH.test(text)) return null;
  if (text.includes("://") || text.includes("\\") || text.includes("//")) return null;
  const path = text.split("?")[0] ?? text;
  if (!SAFE_PREFIXES.some((prefix) => path === prefix || path.startsWith(`${prefix}/`))) return null;
  return text;
}

export function safeId(value: string | null | undefined): string | null {
  if (!value) return null;
  const text = value.trim();
  return SAFE_ID.test(text) ? text : null;
}

export function safeCapabilityRef(value: string | null | undefined): string | null {
  if (!value) return null;
  const text = value.trim();
  return SAFE_CAPABILITY.test(text) ? text : null;
}

export function marketplaceHref(input: {
  slug?: string;
  capabilityRef?: string;
  returnTo?: string | null;
  nodeId?: string | null;
  designSessionId?: string | null;
}): string {
  const params = new URLSearchParams();
  params.set("applies_to", "WORKFLOWS");
  if (input.slug && safeId(input.slug.replaceAll("_", "-"))) {
    params.set("q", input.slug);
  } else if (input.slug && /^[a-z0-9][a-z0-9-]{0,80}$/.test(input.slug)) {
    params.set("q", input.slug);
  }
  const capability = safeCapabilityRef(input.capabilityRef);
  if (capability) params.set("capability_ref", capability);
  const nodeId = safeId(input.nodeId);
  if (nodeId) params.set("node_id", nodeId);
  const sessionId = safeId(input.designSessionId);
  if (sessionId) params.set("design_session_id", sessionId);
  const back = safeReturnTo(input.returnTo);
  if (back) params.set("return_to", back);
  return `/marketplace?${params.toString()}`;
}
