// =============================================================================
// SourceEvolution — cada archivo muestra su propio aprendizaje
// =============================================================================
// Leyendo · Comprendiendo · Organizando · Conectando · Verificando · Aprendido
// con los conteos reales que produjo cada fuente. Excel/CSV tiene su propia
// representación (hojas, tablas, columnas, filas, claves) y las tablas que
// ZENT reconoció, sin pintar filas individuales.
// =============================================================================
import { useMemo, useState } from "react";
import {
  CaretDown,
  CheckCircle,
  Circle,
  CircleNotch,
  FileText,
  Table,
  WarningCircle,
} from "@phosphor-icons/react";

import { timeAgo } from "../../lib/format";
import type { SessionEvent, SessionSource } from "../../lib/knowledgeSessions";
import { deriveRecognizedTables } from "./learningInsights";

const STATUS_COPY: Record<string, string> = {
  pending: "En espera",
  learning: "Aprendiendo",
  available: "Disponible para consultar",
  completed: "Conocimiento integrado",
  failed: "Quedó parcialmente aprendida",
};

const STAGE_ORDER = [
  "reading",
  "understanding",
  "organizing",
  "connecting",
  "verifying",
  "learned",
];

const STAGE_LABELS: Record<string, string> = {
  reading: "Leyendo",
  understanding: "Comprendiendo",
  organizing: "Organizando",
  connecting: "Conectando",
  verifying: "Verificando",
  learned: "Aprendido",
};

const STAGE_STATS: Record<string, Array<[string, string]>> = {
  reading: [
    ["pages", "páginas"],
    ["sections", "secciones"],
    ["records", "registros"],
  ],
  understanding: [["semantic_units", "unidades"]],
  organizing: [
    ["entities", "conceptos"],
    ["tables", "tablas"],
    ["columns", "columnas"],
  ],
  connecting: [
    ["relationships", "relaciones"],
    ["merges", "fusiones"],
  ],
  verifying: [
    ["evidence", "evidencias"],
    ["conflicts", "conflictos"],
    ["duplicates", "duplicados"],
  ],
  learned: [["knowledge_objects", "objetos"]],
};

function StageChecklist({ source }: { source: SessionSource }) {
  const stats = source.stats ?? {};
  const status = source.status;
  const currentIndex = STAGE_ORDER.indexOf(source.stage);
  const done = status === "completed";
  return (
    <ol className="ks-stage-checks" aria-label={`Etapas de ${source.name}`}>
      {STAGE_ORDER.map((stage, index) => {
        const state = done
          ? "done"
          : index < currentIndex
            ? "done"
            : index === currentIndex
              ? "current"
              : "pending";
        const details = (STAGE_STATS[stage] ?? [])
          .map(([key, label]) => {
            const value = Number(stats[key] ?? 0);
            return value > 0
              ? `${value.toLocaleString("es-PE")} ${label}`
              : null;
          })
          .filter(Boolean) as string[];
        return (
          <li key={stage} className="ks-stage-check" data-state={state}>
            <span className="ks-stage-check-icon" aria-hidden>
              {state === "done" ? (
                <CheckCircle size={13} weight="fill" className="text-ok" />
              ) : state === "current" ? (
                <CircleNotch size={13} className="ks-spin text-accent" />
              ) : (
                <Circle size={13} className="text-faint" />
              )}
            </span>
            <span className="ks-stage-check-label">{STAGE_LABELS[stage]}</span>
            {details.length > 0 && (
              <span className="ks-stage-check-detail">{details.join(" · ")}</span>
            )}
          </li>
        );
      })}
    </ol>
  );
}

function TabularSpine({ stats }: { stats: Record<string, number> }) {
  const nodes = [
    { key: "sheets", label: "hojas" },
    { key: "tables", label: "tablas" },
    { key: "columns", label: "columnas" },
    { key: "rows", label: "filas" },
    { key: "candidate_keys", label: "claves candidatas" },
    { key: "table_relations", label: "relaciones entre tablas" },
  ].filter((node) => (stats[node.key] ?? 0) > 0);
  if (nodes.length === 0) return null;
  return (
    <ol className="ks-spine" data-testid="tabular-spine" aria-label="Estructura tabular">
      {nodes.map((node) => (
        <li key={node.key} className="ks-spine-item">
          <span className="ks-spine-icon" aria-hidden>
            <Table size={13} />
          </span>
          <span className="ks-spine-label">{node.label}</span>
          <span className="ks-spine-value font-mono tabular-nums">
            {(stats[node.key] ?? 0).toLocaleString("es-PE")}
          </span>
        </li>
      ))}
    </ol>
  );
}

export function SourceEvolution({
  sources,
  events = [],
}: {
  sources: SessionSource[];
  events?: SessionEvent[];
}) {
  const [open, setOpen] = useState<string | null>(null);
  const ordered = useMemo(() => sources, [sources]);

  return (
    <ul className="ks-sources" data-testid="source-evolution">
      {ordered.map((source) => {
        const stats = source.stats ?? {};
        const isTabular =
          ["excel", "csv"].includes(source.source_type) || (stats.sheets ?? 0) > 0;
        const failed = source.status === "failed";
        const done = source.status === "completed";
        const working = source.status === "learning" || source.status === "pending";
        const recognizedTables = isTabular
          ? deriveRecognizedTables(events, source.source_id)
          : [];
        return (
          <li key={source.id} className="ks-source" data-status={source.status}>
            <button
              type="button"
              className="ks-source-head"
              onClick={() => setOpen(open === source.id ? null : source.id)}
              aria-expanded={open === source.id}
            >
              <span className="ks-source-icon" aria-hidden>
                {failed ? (
                  <WarningCircle size={17} weight="fill" className="text-danger" />
                ) : done ? (
                  <CheckCircle size={17} weight="fill" className="text-ok" />
                ) : working ? (
                  <CircleNotch size={17} className="ks-spin text-accent" />
                ) : (
                  <FileText size={17} className="text-info" />
                )}
              </span>
              <span className="min-w-0 flex-1 text-left">
                <span className="ks-source-name" title={source.name}>
                  {source.name}
                </span>
                <span className="ks-source-meta">
                  <span>{STATUS_COPY[source.status] ?? source.status}</span>
                  {done && source.completed_at && (
                    <span className="text-faint">· {timeAgo(source.completed_at)}</span>
                  )}
                  {!done && <span className="text-faint">· {source.stage_label}</span>}
                </span>
              </span>
              <CaretDown
                size={13}
                className={`ks-feed-caret ${open === source.id ? "is-open" : ""}`}
                aria-hidden
              />
            </button>

            {failed && source.error && (
              <div className="ks-source-error">
                <p>{source.error}</p>
                <details>
                  <summary>Detalle técnico</summary>
                  <p className="font-mono text-[11px] break-words">
                    {String(stats.__technical ?? "sin detalle adicional")}
                  </p>
                </details>
              </div>
            )}

            {(open === source.id || source.status === "completed") && (
              <div className="ks-source-body">
                {isTabular && <TabularSpine stats={stats} />}
                {recognizedTables.length > 0 && (
                  <div className="ks-recognized">
                    <span className="text-[11px] text-faint">ZENT reconoció:</span>
                    <ul>
                      {recognizedTables.map((name) => (
                        <li key={name} className="badge badge-muted">
                          {name}
                        </li>
                      ))}
                    </ul>
                  </div>
                )}
                <StageChecklist source={source} />
                {source.status !== "failed" && (
                  <p className="ks-source-status-line">
                    {done ? (
                      <>
                        <CheckCircle size={13} weight="fill" className="text-ok" />
                        Conocimiento integrado
                      </>
                    ) : working ? (
                      <>
                        <CircleNotch size={13} className="ks-spin text-accent" />
                        {source.stage_label}…
                      </>
                    ) : (
                      <>
                        <CheckCircle size={13} weight="fill" className="text-info" />
                        Ya puede responder preguntas; ZENT sigue enriqueciendo su
                        conocimiento.
                      </>
                    )}
                  </p>
                )}
              </div>
            )}
          </li>
        );
      })}
    </ul>
  );
}

export default SourceEvolution;
