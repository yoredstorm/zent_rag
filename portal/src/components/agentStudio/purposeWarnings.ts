/** Traduce los avisos del generador de propósito a texto legible (nada callado). */
export function describeWarnings(warnings: string[]): string {
  return warnings
    .map((warning) => {
      if (warning.startsWith("mentions_unconfigured_capability:")) {
        const caps = warning
          .slice("mentions_unconfigured_capability:".length)
          .split(",")
          .filter(Boolean);
        return `Se quitó una frase que mencionaba capacidades no configuradas (${caps.join(", ")}).`;
      }
      if (warning === "empty_model_output") {
        return "El modelo no devolvió texto: se propuso un borrador por reglas.";
      }
      if (warning === "purpose_replaced_by_rules") {
        return "Se propuso un borrador por reglas a partir de los datos del agente.";
      }
      return warning;
    })
    .join(" ");
}
