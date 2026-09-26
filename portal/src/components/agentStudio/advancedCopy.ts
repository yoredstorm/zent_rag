// =============================================================================
// advancedCopy — copy de la configuración avanzada del Agent Studio.
// =============================================================================
// Regla: primero el nombre entendible, después el identificador técnico. Quien
// ya conoce `zent-default` o `top_k` los sigue encontrando; quien no, entiende
// igual. Los defaults recomendados viven en `agentModes.ts`.
// =============================================================================
import { MODEL_PRIORITIES } from "./agentModes";

export type Choice = { value: string; label: string; tech: string };

/** Texto de un `<option>`: nombre entendible + alias técnico. */
export function choiceOptionLabel(choice: Choice): string {
  return `${choice.label} · ${choice.tech}`;
}

export const CUSTOM_MODEL_VALUE = "__custom__";

/** Espejo de las rutas del gateway: el usuario elige prioridad, no motor. */
export const GATEWAY_ROUTES: Choice[] = MODEL_PRIORITIES;

export const RETRIEVAL_STRATEGIES: Choice[] = [
  { value: "vector", label: "Por significado", tech: "vector" },
  { value: "lexical", label: "Por palabras exactas", tech: "lexical" },
  { value: "hybrid", label: "Combina ambos", tech: "hybrid" },
];

export type ToolChoice = { tool: string; label: string; hint: string };

/** Tool real → nombre humano. Es la traducción que ve el usuario. */
export const TOOL_CHOICES: ToolChoice[] = [
  {
    tool: "search_knowledge",
    label: "Consultar conocimiento",
    hint: "Lee tus documentos y tablas antes de responder.",
  },
  {
    tool: "query_database",
    label: "Consultar datos",
    hint: "Ejecuta consultas SQL de solo lectura sobre tus datos conectados.",
  },
  {
    tool: "call_api",
    label: "Usar integraciones externas",
    hint: "Usa integraciones y servicios fuera de Zent para traer o enviar datos.",
  },
];

export const TECH_TOOL_LABELS: Record<string, string> = {
  search_knowledge: "Consultar conocimiento",
  query_tabular_data: "Consultar tablas",
  query_database: "Consultar datos",
  call_api: "Integraciones externas",
};

export function toolHumanLabel(tool: string): string {
  return TECH_TOOL_LABELS[tool] ?? tool;
}

export const COPY = {
  model: {
    label: "Prioridad del motor",
    hint: "Zent elige el motor real por ti. Aquí decides si prioriza velocidad, costo o calidad.",
    customLabel: "Modelo específico",
    customHint: "Nombre exacto del modelo en el proveedor, por ejemplo openai/gpt-4o-mini.",
  },
  temperature: {
    label: "Creatividad",
    hint: "Bajo: responde casi siempre igual. Alto: varía más las palabras y arriesga más (temperature).",
    min: "Preciso",
    max: "Variado",
  },
  output: {
    label: "Formato de respuesta (JSON, opcional)",
    hint: "Vacío: responde en texto libre. Con campos: responde siempre con ese JSON, útil para conectarlo a otro sistema.",
    invalid: "JSON inválido. Revisa la sintaxis.",
  },
  tools: {
    title: "Herramientas",
    hint: "Qué información puede consultar el agente. Zent decide cómo consultarla.",
  },
  retrieval: {
    title: "Cómo busca en tus fuentes",
    hint: "Aplica cuando el agente puede buscar en el conocimiento.",
    strategyLabel: "Forma de buscar",
    strategyHint: "Por significado entiende sinónimos. Por palabras exactas sirve para códigos y nombres propios.",
    topKLabel: "Fragmentos a usar",
    topKHint: "Cuántos trozos de tus documentos lee antes de responder (top_k). Más contexto cuesta más.",
    thresholdLabel: "Similitud mínima",
    thresholdHint: "0 no filtra nada. Sube si trae resultados poco relacionados (score_threshold).",
  },
  limits: {
    title: "Límites y costos",
    hint: "Cortan al agente si se pasa. Protegen tu gasto y evitan bucles.",
    stepsLabel: "Tope de pasos",
    stepsHint: "Cuántas veces puede pensar o usar herramientas en un mismo turno (max_steps).",
    tokensLabel: "Tope de texto (tokens)",
    tokensHint: "Largo máximo entre lo que lee y lo que responde (max_tokens).",
    costLabel: "Tope de costo (USD)",
    costHint: "Gasto máximo de una sola respuesta (max_cost_usd).",
  },
  publish: {
    versionsTitle: "Versiones",
    versionsHint: "Cada versión congela la configuración actual (snapshot) para poder volver a ella.",
    deployTitle: "Publicar en un entorno",
    deployHint: "Publicar deja la versión elegida atendiendo en ese entorno.",
    embedTitle: "Widget para tu web",
    embedHint: "Genera un token y pega el código en tu sitio para que el agente atienda ahí.",
    evaluationTitle: "Evaluación",
    evaluationHint: "Mide la calidad del agente con conjuntos de prueba antes de publicar.",
    gatesTitle: "Reglas de calidad antes de publicar",
  },
} as const;

export const ADVANCED_SUMMARY_TITLE = "Configuración avanzada";
export const ADVANCED_SUMMARY_HINT = "modelo, respuesta, herramientas, búsqueda, JEV, límites e integración";
