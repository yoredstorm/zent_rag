/**
 * Errores humanos del workflow (misión §24).
 * Traduce mensajes técnicos del motor a lenguaje de negocio; Advanced sigue
 * viendo el detalle original en los paneles de runs.
 */

const RULES: { match: RegExp; translate: (m: RegExpMatchArray, original: string) => string }[] = [
  {
    match: /permiso insuficiente:\s*(.+)/i,
    translate: (m) =>
      `Tu usuario no tiene permiso para ejecutar este paso (${m[1].trim()}). Pide acceso a un administrador.`,
  },
  {
    match: /tipo de nodo desconocido:\s*(.+)/i,
    translate: (m) =>
      `Este flujo usa un tipo de paso que Zent no reconoce (${m[1].trim()}). Edítalo en modo Avanzado.`,
  },
  {
    match: /no tiene puerto de (salida|entrada)\s*(.*)/i,
    translate: () => "Una conexión del flujo no es válida. Revísala en modo Avanzado.",
  },
  {
    match: /tipo\s+(\w+)\s+no compatible con\s+(\w+)/i,
    translate: () => "Dos pasos están conectados con datos que no son compatibles. Revísalo en modo Avanzado.",
  },
  {
    match: /el agente\s+(.+?)\s+no está disponible/i,
    translate: (m) => `El agente ${m[1]} ya no está disponible. Elige otro agente en este paso.`,
  },
  {
    match: /knowledge_base_id no pertenece/i,
    translate: () => "La base de conocimiento elegida no está disponible. Elige otra en este paso.",
  },
  {
    match: /necesitas conectar\s+(.+?)\s+para usar esta acción/i,
    translate: (m) => `Necesitas conectar ${m[1]} para usar esta acción.`,
  },
  {
    match: /la acción «?(.+?)»? no está instalada/i,
    translate: (m) => `La acción ${m[1]} no está instalada. Instálala desde el canvas o elige otra.`,
  },
  {
    match: /no encontramos el campo\s+(.+?)\s+en la salida/i,
    translate: (_m, original) => original,
  },
  {
    match: /call_api blocked/i,
    translate: () => "La llamada a un servicio externo está bloqueada para tu organización. Pide habilitar el dominio.",
  },
  {
    match: /host '(.+?)' not in tenant api_allowlist/i,
    translate: (m) => `El servicio ${m[1]} no está autorizado en tu organización. Pide habilitarlo.`,
  },
  {
    match: /invalid reference\s+(.+)/i,
    translate: (m) => `No encontramos el dato ${m[1]} en la salida del paso anterior. Elige de nuevo el dato.`,
  },
  {
    match: /integration missing/i,
    translate: () => "Necesitas conectar la integración para usar esta acción.",
  },
];

export function humanizeWorkflowError(message: string | null | undefined): string {
  const original = String(message ?? "").trim();
  if (!original) return "";
  for (const rule of RULES) {
    const match = original.match(rule.match);
    if (match) return rule.translate(match, original);
  }
  return original;
}
