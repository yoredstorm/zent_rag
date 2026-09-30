export function formatProbability(value: number | null | undefined): string | null {
  if (typeof value !== "number" || !Number.isFinite(value) || value < 0 || value > 1) {
    return null;
  }
  const percent = value * 100;
  return `${percent.toFixed(percent % 1 === 0 ? 0 : 1)}%`;
}
