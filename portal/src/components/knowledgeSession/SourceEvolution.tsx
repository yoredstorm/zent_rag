// =============================================================================
// SourceEvolution — cada fuente muestra lo que ZENT realmente comprendió
// =============================================================================
// Nunca "100% completado": se listan hitos verificables (leído, estructura,
// páginas, entidades, hechos, relaciones, evidencias, conocimiento integrado).
// Excel/CSV tiene su propia representación: hoja -> tablas -> columnas ->
// relaciones, sin intentar pintar 13.000 filas.
// =============================================================================
import { useMemo, useState } from "react";
import {
  CaretDown,
  CheckCircle,
  CircleNotch,
  FileText,
  Table,
  WarningCircle,
} from "@phosphor-icons/react";

import { timeAgo } from "../../lib/format";
import type { SessionSource } from "../../lib/knowledgeSessions";

const STATUS_COPY: Record<string, string> = {
  pending: "En espera",
  learning: "Aprendiendo",
  available: "Disponible para consultar",
  completed: "Conocimiento integrado",
  failed: "Quedó parcialmente aprendida",
};

function Stat({ value, label }: { value: number; label: string }) {
  return (
    <li>
      <span className="ks-check" aria-hidden>
        <CheckCircle size={13} weight="fill" />
      </span>
      <span className="text-[13px] text-text">
        <span className="font-mono tabular-nums">{value.toLocaleString("es-PE")}</span>{" "}
        {label}
      </span>
    </li>
  );
}

function TabularSpine({ stats }: { stats: Record<string, number> }) {
  const nodes = [
    { key: "sheets", label: "hojas", icon: <Table size={13} /> },
    { key: "tables", label: "tablas", icon: <Table size={13} /> },
    { key: "columns", label: "columnas", icon: <Table size={13} /> },
    { key: "table_relations", label: "relaciones", icon: <Table size={13} /> },
  ].filter((node) => (stats[node.key] ?? 0) > 0);
  if (nodes.length === 0) return null;
  return (
    <ol className="ks-spine" data-testid="tabular-spine" aria-label="Estructura tabular">
      {nodes.map((node) => (
        <li key={node.key} className="ks-spine-item">
          <span className="ks-spine-icon" aria-hidden>
            {node.icon}
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

export function SourceEvolution({ sources }: { sources: SessionSource[] }) {
  const [open, setOpen] = useState<string | null>(null);
  const ordered = useMemo(() => sources, [sources]);

  return (
    <ul className="ks-sources" data-testid="source-evolution">
      {ordered.map((source) => {
        const stats = source.stats ?? {};
        const isTabular =
          ["excel", "csv"].includes(source.source_type) ||
          (stats.sheets ?? 0) > 0;
        const failed = source.status === "failed";
        const done = source.status === "completed";
        const working = source.status === "learning" || source.status === "pending";
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
                {isTabular ? (
                  <TabularSpine stats={stats} />
                ) : (
                  <ul className="ks-checks">
                    {stats.pages ? <Stat value={stats.pages} label="páginas analizadas" /> : null}
                    {stats.sections ? (
                      <Stat value={stats.sections} label="secciones comprendidas" />
                    ) : null}
                    {stats.tables ? <Stat value={stats.tables} label="tablas detectadas" /> : null}
                  </ul>
                )}
                <ul className="ks-checks">
                  {stats.entities ? <Stat value={stats.entities} label="entidades" /> : null}
                  {stats.facts ? <Stat value={stats.facts} label="hechos" /> : null}
                  {stats.relationships ? (
                    <Stat value={stats.relationships} label="relaciones" />
                  ) : null}
                  {stats.rules ? <Stat value={stats.rules} label="reglas" /> : null}
                  {stats.evidence ? <Stat value={stats.evidence} label="evidencias" /> : null}
                  {stats.ignored ? (
                    <Stat value={stats.ignored} label="fragmentos duplicados consolidados" />
                  ) : null}
                </ul>
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
