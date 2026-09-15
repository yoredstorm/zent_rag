// Copy en español del panel "Ajustes extra" del Agent Studio.
// Los identificadores técnicos (zent-default, search_knowledge, top_k…) se
// muestran como pista secundaria: quien ya los conoce los sigue encontrando.

export const ADVANCED_SUMMARY_TITLE = "Ajustes extra";
export const ADVANCED_SUMMARY_HINT = "modelo, herramientas, versiones y publicación";

export type Choice = { value: string; label: string; tech: string };

/** Texto de un `<option>`: nombre entendible + alias técnico. */
export function choiceOptionLabel(choice: Choice): string {
  return `${choice.label} · ${choice.tech}`;
}

export const CUSTOM_MODEL_VALUE = "__custom__";

export const GATEWAY_ROUTES: Choice[] = [
  { value: "zent-default", label: "Equilibrado (recomendado)", tech: "zent-default" },
  { value: "zent-fast", label: "Rápido", tech: "zent-fast" },
  { value: "zent-cheap", label: "Económico", tech: "zent-cheap" },
  { value: "zent-quality", label: "Máxima calidad", tech: "zent-quality" },
  { value: "zent-routed", label: "Automático según reglas", tech: "zent-routed" },
];

export const TONE_CHOICES: { value: string; label: string; hint: string }[] = [
  { value: "professional", label: "Profesional", hint: "formal y directo" },
  { value: "friendly", label: "Cercano", hint: "cálido y conversacional" },
  { value: "concise", label: "Conciso", hint: "lo mínimo para responder" },
];

export const RETRIEVAL_STRATEGIES: Choice[] = [
  { value: "vector", label: "Por significado", tech: "vector" },
  { value: "lexical", label: "Por palabras exactas", tech: "lexical" },
  { value: "hybrid", label: "Combina ambos", tech: "hybrid" },
];

export type ToolChoice = { tool: string; label: string; hint: string };

export const TOOL_CHOICES: ToolChoice[] = [
  {
    tool: "search_knowledge",
    label: "Buscar en el conocimiento",
    hint: "Lee tus fuentes y documentos antes de responder.",
  },
  {
    tool: "query_database",
    label: "Consultar la base de datos",
    hint: "Escribe y ejecuta consultas SQL de solo lectura sobre tus datos conectados.",
  },
  {
    tool: "call_api",
    label: "Llamar APIs externas",
    hint: "Usa integraciones y servicios fuera de Zent para traer o enviar datos.",
  },
];

export const COPY = {
  model: {
    label: "Qué modelo usar",
    hint: "Zent elige el motor real por ti. Aquí decides si prioriza velocidad, costo o calidad.",
    customLabel: "Modelo propio",
    customHint: "Nombre exacto del modelo en el proveedor, por ejemplo openai/gpt-4o-mini.",
  },
  temperature: {
    label: "Creatividad",
    hint: "Bajo: responde casi siempre igual. Alto: varía más las palabras y arriesga más (temperature).",
    min: "Preciso",
    max: "Variado",
  },
  tone: {
    label: "Tono",
    hint: "Matiz sobre tus instrucciones. Si el propósito ya define el estilo, deja Profesional.",
  },
  output: {
    label: "Formato de respuesta (JSON, opcional)",
    hint: "Vacío: responde en texto libre. Con campos: responde siempre con ese JSON, útil para conectarlo a otro sistema.",
    invalid: "JSON inválido. Revisa la sintaxis.",
  },
  tools: {
    title: "Herramientas",
    hint: "Cada herramienta activa le da un permiso extra al agente. Enciende solo las que necesite.",
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
    title: "Topes por respuesta",
    hint: "Cortan al agente si se pasa. Protegen tu gasto y evitan bucles.",
    stepsLabel: "Tope de pasos",
    stepsHint: "Cuántas veces puede pensar o usar herramientas en un mismo turno.",
    tokensLabel: "Tope de texto (tokens)",
    tokensHint: "Largo máximo entre lo que lee y lo que responde.",
    costLabel: "Tope de costo (USD)",
    costHint: "Gasto máximo de una sola respuesta.",
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
