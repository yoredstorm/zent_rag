// =============================================================================
// KnowledgeConfidenceBadge — confianza numérica real (nunca inventada)
// =============================================================================
export function KnowledgeConfidenceBadge({
  confidence,
  label,
  compact = false,
}: {
  confidence: number | null | undefined;
  label?: string | null;
  compact?: boolean;
}) {
  const pct = Math.round(Math.max(0, Math.min(1, confidence ?? 0)) * 100);
  const tone = pct >= 80 ? "badge-ok" : pct >= 55 ? "badge-pending" : "badge-muted";
  const title = label ? `Confianza ${label} (${pct}%)` : `Confianza ${pct}%`;
  return (
    <span className={`badge ${tone}`} title={title}>
      {compact ? `${pct}%` : `${pct}% confianza`}
    </span>
  );
}
