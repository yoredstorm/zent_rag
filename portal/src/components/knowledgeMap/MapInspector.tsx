// =============================================================================
// MapInspector — la ficha viva de un nodo del Knowledge Map
// =============================================================================
// Entity card + knowledge strength explicable + relaciones + evidence path
// ("¿cómo sabe ZENT esto?") + timeline + conflictos. Todo del detalle real.
// =============================================================================
import { useCallback, useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import {
  ArrowRight,
  ChatCircleDots,
  ClockCounterClockwise,
  FileText,
  Graph,
  Info,
  MagnifyingGlass,
  Path,
  WarningCircle,
} from "@phosphor-icons/react";

import { api, loadSession } from "../../api";
import {
  fetchKnowledgeConflicts,
  fetchKnowledgeObject,
  objectTypeLabel,
  statusTone,
  type KnowledgeConflict,
  type KnowledgeObjectDetail,
} from "../../lib/knowledgeModel";
import { fmtDateTime, timeAgo } from "../../lib/format";
import { Badge, ButtonLink, ErrorInline, Skeleton, cn } from "../ui";
import { KnowledgeConfidenceBadge } from "../knowledgeLearning/KnowledgeConfidenceBadge";
import { ConflictCard } from "../knowledge/ConflictCard";
import { Tooltip } from "../ui/overlay";
import {
  buildEvidencePath,
  buildTimeline,
  deriveKnowledgeStrength,
} from "./mapInsights";

type InspectorTab = "resumen" | "relaciones" | "evidencia" | "timeline" | "conflictos";

const TABS: { id: InspectorTab; label: string }[] = [
  { id: "resumen", label: "Resumen" },
  { id: "relaciones", label: "Relaciones" },
  { id: "evidencia", label: "Evidencia" },
  { id: "timeline", label: "Timeline" },
  { id: "conflictos", label: "Conflictos" },
];

function SectionTitle({
  title,
  hint,
}: {
  title: string;
  hint: string;
}) {
  return (
    <span className="flex items-center gap-1.5">
      <span className="eyebrow">{title}</span>
      <Tooltip label={hint}>
        <button
          type="button"
          className="inline-flex h-4 w-4 items-center justify-center rounded-full text-ghost hover:text-muted"
          aria-label={`Qué significa ${title}`}
        >
          <Info size={11} aria-hidden />
        </button>
      </Tooltip>
    </span>
  );
}

export function MapInspector({
  objectId,
  onClose,
}: {
  objectId: string | null;
  onClose?: () => void;
}) {
  const [detail, setDetail] = useState<KnowledgeObjectDetail | null>(null);
  const [conflicts, setConflicts] = useState<KnowledgeConflict[]>([]);
  const [sourceNames, setSourceNames] = useState<Record<string, string>>({});
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [tab, setTab] = useState<InspectorTab>("resumen");

  const load = useCallback(async () => {
    if (!objectId) return;
    setLoading(true);
    setError("");
    try {
      const data = await fetchKnowledgeObject(objectId);
      setDetail(data);
      setTab("resumen");
      try {
        const all = await fetchKnowledgeConflicts("open");
        setConflicts(all.conflicts.filter((item) => item.object_id === objectId));
      } catch {
        setConflicts([]);
      }
      const sourceIds = [
        ...new Set(
          data.evidence
            .map((evidence) => evidence.source_id)
            .filter((value): value is string => Boolean(value))
        ),
      ].slice(0, 4);
      if (sourceIds.length > 0) {
        const session = loadSession();
        const names: Record<string, string> = {};
        await Promise.allSettled(
          sourceIds.map(async (sourceId) => {
            try {
              const source = await api<{ name?: string }>(
                `/api/v1/sources/${sourceId}`,
                { token: session?.token, organizationId: session?.organizationId }
              );
              if (source?.name) names[sourceId] = source.name;
            } catch {
              // El nombre es cosmético: si falla, queda el id corto.
            }
          })
        );
        setSourceNames(names);
      }
    } catch (err) {
      setDetail(null);
      setError(err instanceof Error ? err.message : "No pudimos abrir el objeto.");
    } finally {
      setLoading(false);
    }
  }, [objectId]);

  useEffect(() => {
    void load();
  }, [load]);

  const strength = useMemo(
    () => deriveKnowledgeStrength(detail, { conflicts: conflicts.length }),
    [detail, conflicts.length]
  );
  const evidencePath = useMemo(
    () => buildEvidencePath(detail, sourceNames),
    [detail, sourceNames]
  );
  const timeline = useMemo(() => buildTimeline(detail), [detail]);
  const outgoing = (detail?.edges ?? []).filter((edge) => edge.direction !== "in");
  const incoming = (detail?.edges ?? []).filter((edge) => edge.direction === "in");

  if (!objectId) {
    return (
      <aside className="km-inspector" data-testid="knowledge-map-inspector">
        <div className="km-inspector-empty">
          <Graph size={20} className="text-faint" aria-hidden />
          <p className="text-[13px] text-muted">
            Selecciona un nodo para inspeccionar qué sabe ZENT, cómo se conecta y
            de dónde salió.
          </p>
        </div>
      </aside>
    );
  }

  return (
    <aside className="km-inspector" data-testid="knowledge-map-inspector">
      {loading && !detail && (
        <div className="flex flex-col gap-3 p-4" aria-busy="true">
          <Skeleton className="h-6 w-2/3 rounded-sm" />
          <Skeleton className="h-20 rounded-md" />
          <Skeleton className="h-32 rounded-md" />
        </div>
      )}

      {!loading && error && (
        <div className="p-4">
          <ErrorInline message={error} className="mb-0" />
        </div>
      )}

      {detail && (
        <>
          <header className="km-inspector-head">
            <div className="flex items-start justify-between gap-2">
              <div className="min-w-0">
                <div className="flex flex-wrap items-center gap-1.5">
                  <span className="badge badge-muted">
                    {objectTypeLabel(detail.object.type)}
                  </span>
                  <span className={cn("badge", statusTone(detail.object.status))}>
                    {detail.object.status}
                  </span>
                  {detail.object.confidence != null && (
                    <KnowledgeConfidenceBadge confidence={detail.object.confidence} />
                  )}
                </div>
                <h2 className="mt-1.5 truncate text-[17px] font-semibold text-text">
                  {detail.object.display_name || detail.object.name}
                </h2>
                {detail.object.description && (
                  <p className="mt-1 line-clamp-3 text-[12px] leading-relaxed text-muted">
                    {detail.object.description}
                  </p>
                )}
              </div>
              {onClose && (
                <button
                  type="button"
                  className="text-[11px] text-faint hover:text-text"
                  onClick={onClose}
                >
                  Cerrar
                </button>
              )}
            </div>

            <div className="km-inspector-metrics">
              <span>
                <strong>{detail.edges.length}</strong> relaciones
              </span>
              <span>
                <strong>{detail.evidence.length}</strong> evidencias
              </span>
              <span>
                <strong>{detail.assertions.length}</strong> hechos
              </span>
              {conflicts.length > 0 ? (
                <span className="text-warn">
                  <strong>{conflicts.length}</strong> conflictos
                </span>
              ) : (
                <span className="text-ok">sin conflictos</span>
              )}
            </div>

            <div className="km-inspector-actions">
              <ButtonLink
                to={`/knowledge/objects/${detail.object.id}`}
                size="sm"
                variant="secondary"
                leadingIcon={MagnifyingGlass}
              >
                Explorar
              </ButtonLink>
              <ButtonLink
                to={`/chat?q=${encodeURIComponent(
                  `¿Qué sabes sobre ${detail.object.display_name || detail.object.name}?`
                )}`}
                size="sm"
                variant="secondary"
                leadingIcon={ChatCircleDots}
              >
                Preguntar
              </ButtonLink>
              {detail.object.source_id && (
                <ButtonLink
                  to={`/knowledge/sources/${detail.object.source_id}`}
                  size="sm"
                  variant="ghost"
                  leadingIcon={FileText}
                >
                  Ver fuentes
                </ButtonLink>
              )}
            </div>
          </header>

          <nav className="km-inspector-tabs" aria-label="Detalle del objeto">
            {TABS.map((item) => (
              <button
                key={item.id}
                type="button"
                className={cn("km-inspector-tab", tab === item.id && "is-active")}
                aria-pressed={tab === item.id}
                onClick={() => setTab(item.id)}
              >
                {item.label}
                {item.id === "conflictos" && conflicts.length > 0 && (
                  <span className="ml-1 text-warn">{conflicts.length}</span>
                )}
              </button>
            ))}
          </nav>

          <div className="km-inspector-body">
            {tab === "resumen" && (
              <div className="flex flex-col gap-4">
                <section>
                  <SectionTitle
                    title="Knowledge strength"
                    hint={strength.explanation}
                  />
                  <div className="mt-2 flex items-center gap-3">
                    <span
                      className={cn(
                        "mono text-[22px] font-semibold tabular-nums",
                        strength.score == null
                          ? "text-faint"
                          : strength.score >= 0.85
                            ? "text-ok"
                            : strength.score >= 0.6
                              ? "text-info"
                              : "text-warn"
                      )}
                    >
                      {strength.score != null
                        ? `${Math.round(strength.score * 100)}%`
                        : "—"}
                    </span>
                    <span className="text-[12px] text-muted">{strength.label}</span>
                  </div>
                  <ul className="km-strength-list">
                    {strength.components.map((component) => (
                      <li key={component.key}>
                        <Tooltip label={component.hint}>
                          <span className="cursor-help text-[12px] text-muted">
                            {component.label}
                          </span>
                        </Tooltip>
                        <span className="flex items-center gap-2">
                          {component.value != null && (
                            <span className="km-strength-bar" aria-hidden>
                              <span
                                style={{
                                  width: `${Math.round(component.value * 100)}%`,
                                }}
                              />
                            </span>
                          )}
                          <span className="mono text-[12px] tabular-nums text-text">
                            {component.display}
                          </span>
                        </span>
                      </li>
                    ))}
                  </ul>
                </section>

                <section>
                  <SectionTitle
                    title="Origen"
                    hint="Procedencia y autoridad registradas por el Knowledge OS."
                  />
                  <dl className="km-kv">
                    <div>
                      <dt>Dominio</dt>
                      <dd>{detail.object.domain || "Sin dominio"}</dd>
                    </div>
                    <div>
                      <dt>Procedencia</dt>
                      <dd>{detail.object.provenance || "—"}</dd>
                    </div>
                    <div>
                      <dt>Actualizado</dt>
                      <dd>{timeAgo(detail.object.updated_at)}</dd>
                    </div>
                    <div>
                      <dt>Primera vez</dt>
                      <dd>{fmtDateTime(detail.object.created_at)}</dd>
                    </div>
                  </dl>
                </section>

                {detail.questions.length > 0 && (
                  <section>
                    <SectionTitle
                      title="Qué falta"
                      hint="Preguntas abiertas de ZENT sobre este objeto."
                    />
                    <ul className="mt-2 flex flex-col gap-1.5">
                      {detail.questions.map((question) => (
                        <li key={question.id} className="flex items-center gap-2">
                          <WarningCircle size={12} className="text-warn" aria-hidden />
                          <span className="min-w-0 flex-1 truncate text-[12px] text-text">
                            {question.title}
                          </span>
                          <Badge tone="neutral">{question.priority}</Badge>
                        </li>
                      ))}
                    </ul>
                  </section>
                )}
              </div>
            )}

            {tab === "relaciones" && (
              <div className="flex flex-col gap-2">
                {detail.edges.length === 0 ? (
                  <p className="text-[13px] text-muted">
                    Este objeto todavía no tiene relaciones registradas.
                  </p>
                ) : (
                  [...outgoing, ...incoming].map((edge) => {
                    const isOut = edge.direction !== "in";
                    const otherId = isOut ? edge.object_id : edge.subject_id;
                    const otherName = isOut
                      ? edge.object_name || edge.object_id
                      : edge.subject_name || edge.subject_id;
                    return (
                      <div key={edge.id} className="km-relation">
                        <div className="flex flex-wrap items-center gap-1.5 text-[12px]">
                          <span className="text-muted">
                            {isOut ? detail.object.name : otherName}
                          </span>
                          <span className="font-medium text-text">{edge.predicate}</span>
                          <Link
                            to={`/knowledge/objects/${otherId}`}
                            className="text-accent hover:underline"
                          >
                            {isOut ? otherName : detail.object.name}
                          </Link>
                        </div>
                        <div className="mt-1 flex flex-wrap items-center gap-2 text-[10px] text-faint">
                          <span>{edge.relationship_type}</span>
                          <span className="mono">
                            confianza {Math.round(edge.confidence * 100)}%
                          </span>
                          <span>{edge.status}</span>
                        </div>
                      </div>
                    );
                  })
                )}
              </div>
            )}

            {tab === "evidencia" && (
              <div className="flex flex-col gap-3">
                <SectionTitle
                  title="¿Cómo sabe ZENT esto?"
                  hint="Camino real: objeto, hecho, evidencia, fuente y página."
                />
                {evidencePath.length <= 1 ? (
                  <p className="text-[13px] text-muted">
                    Este objeto no tiene evidencia localizable todavía. Es una señal
                    de salud: ZENT no lo dará por verificado.
                  </p>
                ) : (
                  <ol className="km-path" data-testid="evidence-path">
                    {evidencePath.map((step) => (
                      <li key={step.id} className={`km-path-step is-${step.kind}`}>
                        <span className="km-path-marker" aria-hidden>
                          {step.kind === "object" ? (
                            <Graph size={11} />
                          ) : step.kind === "evidence" ? (
                            <FileText size={11} />
                          ) : step.kind === "page" ? (
                            <Path size={11} />
                          ) : (
                            <ArrowRight size={11} />
                          )}
                        </span>
                        <span className="min-w-0 flex-1">
                          <span className="block truncate text-[12px] text-text">
                            {step.label}
                          </span>
                          {step.detail && (
                            <span className="block text-[10px] text-faint">
                              {step.detail}
                            </span>
                          )}
                        </span>
                        {step.sourceId && (
                          <Link
                            to={`/knowledge/sources/${step.sourceId}`}
                            className="shrink-0 text-[10px] text-accent hover:underline"
                          >
                            Ver fuente
                          </Link>
                        )}
                      </li>
                    ))}
                  </ol>
                )}
                {detail.evidence.length > 1 && (
                  <p className="text-[11px] text-faint">
                    +{detail.evidence.length - 1} evidencias más en el objeto
                    completo.
                  </p>
                )}
              </div>
            )}

            {tab === "timeline" && (
              <div className="flex flex-col gap-3">
                <SectionTitle
                  title="Historial"
                  hint="Versiones y vigencias reales registradas por el Knowledge OS."
                />
                {timeline.length === 0 ? (
                  <p className="text-[13px] text-muted">
                    Sin cambios registrados desde que ZENT lo conoce.
                  </p>
                ) : (
                  <ol className="km-timeline" data-testid="knowledge-timeline">
                    {timeline.map((entry) => (
                      <li key={entry.id} className="km-timeline-item">
                        <span className="km-timeline-dot" aria-hidden>
                          <ClockCounterClockwise size={11} />
                        </span>
                        <span className="min-w-0 flex-1">
                          <span className="block text-[12px] text-text">
                            {entry.title}
                          </span>
                          {entry.detail && (
                            <span className="block text-[10px] text-faint">
                              {entry.detail}
                            </span>
                          )}
                        </span>
                        <time className="shrink-0 text-[10px] text-faint">
                          {entry.at ? entry.at.slice(0, 10) : "—"}
                        </time>
                      </li>
                    ))}
                  </ol>
                )}
              </div>
            )}

            {tab === "conflictos" && (
              <div className="flex flex-col gap-2">
                {conflicts.length === 0 ? (
                  <p className="text-[13px] text-muted">
                    Sin conflictos abiertos sobre este conocimiento.
                  </p>
                ) : (
                  conflicts.map((conflict) => (
                    <ConflictCard key={conflict.id} conflict={conflict} />
                  ))
                )}
              </div>
            )}
          </div>
        </>
      )}
    </aside>
  );
}

export default MapInspector;
