// =============================================================================
// CognitiveTechnicalCard — nivel expandido/raw del runtime cognitivo (C6).
// =============================================================================
import { parseCognitiveStory } from "../cognitiveStory";

function Row({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <dt className="text-faint">{label}</dt>
      <dd className="text-text">{value}</dd>
    </div>
  );
}

export function CognitiveTechnicalCard({ raw }: { raw?: Record<string, unknown> }) {
  const story = parseCognitiveStory(raw?.cognitive_story);
  if (!story) return null;
  const expanded = story.expanded;
  const strategy = (expanded.strategy ?? {}) as Record<string, unknown>;
  const evidence = (expanded.evidence ?? {}) as Record<string, unknown>;
  const budget = (expanded.budget ?? {}) as Record<string, unknown>;
  const loop = (expanded.loop ?? {}) as Record<string, unknown>;
  const verification = (expanded.verification ?? {}) as Record<string, unknown>;
  const deep = (expanded.deep ?? {}) as Record<string, unknown>;
  return (
    <article className="rounded-lg border border-border bg-surface p-4">
      <p className="eyebrow mb-2">Runtime cognitivo</p>
      <dl className="grid grid-cols-1 gap-x-4 gap-y-2 text-[12px] sm:grid-cols-2">
        <Row label="Modo" value={String(story.raw.run_id ? "run profundo" : "observación")} />
        <Row label="Run" value={String(story.raw.run_id ?? "—")} />
        <Row label="Estrategia" value={String(strategy.primary ?? "—")} />
        <Row label="Evidencia" value={String(evidence.count ?? 0)} />
        <Row label="Conflictos" value={String(evidence.conflicts ?? 0)} />
        <Row label="Verificación" value={String(verification.action ?? "—")} />
        <Row label="Budget" value={budget.within_budget ? "dentro" : "excedido"} />
        <Row label="Rondas" value={String(loop.count ?? 0)} />
        <Row label="Deep" value={String(deep.status ?? "—")} />
      </dl>
    </article>
  );
}

export default CognitiveTechnicalCard;
