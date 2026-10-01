// =============================================================================
// LearningSummary — qué cambió en el cerebro de ZENT
// =============================================================================
// Al terminar NO se muestra "Carga completada": se muestra el delta real del
// Knowledge OS (nuevo, reforzado, actualizado, relacionado, conflictivo,
// ignorado) y el antes/después priorizando el cambio.
// =============================================================================
import {
  ArrowsClockwise,
  CheckCircle,
  CopySimple,
  GitMerge,
  LinkSimple,
  PlusCircle,
  ShieldWarning,
  Sparkle,
  Stack,
  WarningCircle,
} from "@phosphor-icons/react";

import type { ReactNode } from "react";

import type { LearningSessionDetail } from "../../lib/knowledgeSessions";
import { AnimatedNumber } from "./KnowledgePulse";

type CategoryKey =
  | "new"
  | "reinforced"
  | "updated"
  | "related"
  | "conflicting"
  | "ignored";

const TAXONOMY: Array<{
  key: CategoryKey;
  label: string;
  hint: string;
  icon: ReactNode;
  tone: string;
}> = [
  {
    key: "new",
    label: "Nuevo",
    hint: "conocimiento que ZENT no tenía",
    icon: <PlusCircle size={14} weight="fill" className="text-accent" />,
    tone: "text-accent",
  },
  {
    key: "reinforced",
    label: "Reforzado",
    hint: "conocimiento existente respaldado por otra fuente",
    icon: <Stack size={14} weight="fill" className="text-info" />,
    tone: "text-info",
  },
  {
    key: "updated",
    label: "Actualizado",
    hint: "información con nueva versión o vigencia",
    icon: <ArrowsClockwise size={14} weight="bold" className="text-warn" />,
    tone: "text-warn",
  },
  {
    key: "related",
    label: "Relacionado",
    hint: "conexiones nuevas entre conocimiento existente",
    icon: <LinkSimple size={14} weight="bold" className="text-info" />,
    tone: "text-info",
  },
  {
    key: "conflicting",
    label: "Conflictivo",
    hint: "información posiblemente incompatible",
    icon: <ShieldWarning size={14} weight="fill" className="text-warn" />,
    tone: "text-warn",
  },
  {
    key: "ignored",
    label: "Ignorado",
    hint: "duplicados exactos o contenido sin valor semántico",
    icon: <CopySimple size={14} weight="bold" className="text-faint" />,
    tone: "text-faint",
  },
];

function categoryValue(category: CategoryKey, delta: Record<string, number>): number {
  switch (category) {
    case "new":
      return (
        (delta.new_entities ?? 0) +
        (delta.new_facts ?? 0) +
        (delta.new_relationships ?? 0) +
        (delta.new_rules ?? 0) +
        (delta.new_evidence ?? 0)
      );
    case "reinforced":
      return (delta.reinforced_facts ?? 0) + (delta.enriched_entities ?? 0);
    case "updated":
      return delta.updated ?? 0;
    case "related":
      return delta.related ?? 0;
    case "conflicting":
      return delta.conflicts ?? 0;
    case "ignored":
      return delta.ignored ?? 0;
    default:
      return 0;
  }
}

function DeltaTile({
  value,
  label,
  tone = "text-accent",
}: {
  value: number;
  label: string;
  tone?: string;
}) {
  return (
    <div className="ks-delta-tile">
      <span className={`ks-delta-value ${tone}`}>
        +<AnimatedNumber value={value} />
      </span>
      <span className="ks-delta-label">{label}</span>
    </div>
  );
}

const BEFORE_AFTER: Array<{ key: string; label: string }> = [
  { key: "entities", label: "entidades" },
  { key: "relationships", label: "relaciones" },
  { key: "facts", label: "hechos" },
  { key: "rules", label: "reglas" },
  { key: "evidence", label: "evidencias" },
];

export function LearningSummary({
  detail,
  delta,
}: {
  detail: LearningSessionDetail;
  delta: Record<string, number>;
}) {
  const partial = detail.status === "partial" || detail.failed_sources > 0;
  const before = detail.totals_before ?? {};
  const after = detail.totals_after ?? {};

  return (
    <section className="panel ks-summary" data-testid="learning-summary">
      <header className="ks-summary-head">
        {partial ? (
          <WarningCircle size={20} weight="fill" className="text-warn" />
        ) : (
          <CheckCircle size={20} weight="fill" className="text-ok" />
        )}
        <div>
          <p className="eyebrow">
            {partial ? "Aprendizaje parcial" : "Aprendizaje completado"}
          </p>
          <h2 className="text-h2">
            ZENT {partial ? "aprendió parcialmente" : "aprendió"} esta información
          </h2>
          <p className="text-[13px] text-muted">
            {detail.source_count} fuente{detail.source_count === 1 ? "" : "s"} procesada
            {detail.source_count === 1 ? "" : "s"}
            {detail.failed_sources > 0
              ? ` · ${detail.failed_sources} quedó parcialmente aprendida`
              : ""}
          </p>
        </div>
      </header>

      <div className="ks-delta-grid">
        <DeltaTile value={delta.new_entities ?? 0} label="entidades nuevas" />
        <DeltaTile value={delta.new_facts ?? 0} label="hechos incorporados" />
        <DeltaTile value={delta.new_relationships ?? 0} label="relaciones descubiertas" />
        <DeltaTile value={delta.new_rules ?? 0} label="reglas aprendidas" />
        <DeltaTile value={delta.new_evidence ?? 0} label="evidencias vinculadas" />
      </div>

      <div className="ks-summary-secondary">
        <p>
          <strong className="text-text">
            <AnimatedNumber value={delta.enriched_entities ?? 0} />
          </strong>{" "}
          conceptos existentes fueron enriquecidos
        </p>
        <p>
          <strong className="text-text">
            <AnimatedNumber value={delta.reinforced_facts ?? 0} />
          </strong>{" "}
          hechos fueron reforzados por una nueva fuente
        </p>
        <p>
          <strong className="text-text">
            <AnimatedNumber value={delta.duplicates ?? 0} />
          </strong>{" "}
          duplicados fueron consolidados
        </p>
        <p className={delta.conflicts ? "text-warn" : ""}>
          <strong>
            <AnimatedNumber value={delta.conflicts ?? 0} />
          </strong>{" "}
          posibles conflictos necesitan revisión
        </p>
      </div>

      <div className="ks-taxonomy" data-testid="learning-taxonomy">
        {TAXONOMY.map((item) => (
          <div key={item.key} className="ks-taxonomy-item" title={item.hint}>
            <span className="ks-taxonomy-icon">{item.icon}</span>
            <span className="ks-taxonomy-label">{item.label}</span>
            <span className={`ks-taxonomy-value ${item.tone}`}>
              <AnimatedNumber value={categoryValue(item.key, delta)} />
            </span>
          </div>
        ))}
      </div>

      {Object.keys(after).length > 0 && (
        <div className="ks-before-after" data-testid="before-after">
          <p className="eyebrow">Antes / ahora</p>
          <ul>
            {BEFORE_AFTER.map((row) => {
              const from = before[row.key] ?? 0;
              const to = after[row.key] ?? 0;
              const diff = to - from;
              return (
                <li key={row.key}>
                  <span className="text-muted">{row.label}</span>
                  <span className="font-mono tabular-nums text-faint">
                    {from.toLocaleString("es-PE")}
                  </span>
                  <span className="ks-ba-arrow" aria-hidden>
                    →
                  </span>
                  <span className="font-mono tabular-nums text-text">
                    {to.toLocaleString("es-PE")}
                  </span>
                  <span className={`ks-ba-delta ${diff > 0 ? "text-accent" : "text-faint"}`}>
                    {diff >= 0 ? "+" : ""}
                    {diff.toLocaleString("es-PE")}
                  </span>
                </li>
              );
            })}
          </ul>
        </div>
      )}

      {delta.updated > 0 && (
        <p className="ks-summary-note">
          <GitMerge size={14} weight="bold" className="text-warn" />
          {delta.updated} cambios de versión o vigencia detectados.
        </p>
      )}
      {delta.merged_entities > 0 && (
        <p className="ks-summary-note">
          <Sparkle size={14} weight="fill" className="text-info" />
          {delta.merged_entities} entidades se fusionaron con su nodo existente
          sin duplicar conocimiento.
        </p>
      )}
    </section>
  );
}

export default LearningSummary;
