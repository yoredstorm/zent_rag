// Orden canónico de etapas del aprendizaje (espejo del backend).
export const STAGE_ORDER = [
  "reading",
  "understanding",
  "organizing",
  "connecting",
  "verifying",
  "learned",
] as const;

export const STAGE_LABELS: Record<string, string> = {
  reading: "Leyendo",
  understanding: "Entendiendo",
  organizing: "Organizando",
  connecting: "Conectando",
  verifying: "Verificando",
  learned: "Aprendido",
};

export const STAGE_TECHNICAL: Record<string, string> = {
  reading: "parser",
  understanding: "semantic units",
  organizing: "entity resolution",
  connecting: "knowledge graph",
  verifying: "evidence linking",
  learned: "indexes",
};

export function stageLabel(stage: string | null | undefined): string {
  return STAGE_LABELS[String(stage ?? "")] ?? "Leyendo";
}

export function stageIndex(stage: string | null | undefined): number {
  const index = STAGE_ORDER.indexOf(String(stage ?? "") as (typeof STAGE_ORDER)[number]);
  return index < 0 ? 0 : index;
}
