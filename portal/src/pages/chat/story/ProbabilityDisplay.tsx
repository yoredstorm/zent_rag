import { formatProbability } from "./probability";

export function ProbabilityDisplay({
  value,
  fallback = "",
  className = "",
}: {
  value: number | null | undefined;
  fallback?: string;
  className?: string;
}) {
  const formatted = formatProbability(value);
  if (!formatted && !fallback) return null;
  return <span className={className}>{formatted ?? fallback}</span>;
}

export default ProbabilityDisplay;
