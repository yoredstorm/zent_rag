// =============================================================================
// Knowledge Object View — cada conocimiento importante tiene su página
// =============================================================================
import { useCallback, useEffect, useMemo, useState } from "react";
import { Link, useParams } from "react-router-dom";
import {
  ArrowLeft,
  ArrowRight,
  ArrowsLeftRight,
  ClockCounterClockwise,
  FileText,
  GitBranch,
  LinkSimple,
  SealCheck,
  Sparkle,
  WarningCircle,
} from "@phosphor-icons/react";
import {
  Badge,
  Button,
  ButtonLink,
  EmptyState,
  ErrorInline,
  Panel,
  Skeleton,
  Tabs,
  TabsContent,
  TabsList,
  TabsTrigger,
  cn,
} from "../../components/ui";
import { KnowledgeLayout } from "../../components/KnowledgeLayout";
import { KnowledgeConfidenceBadge } from "../../components/knowledgeLearning/KnowledgeConfidenceBadge";
import {
  fetchKnowledgeConflicts,
  fetchKnowledgeObject,
  objectTypeLabel,
  statusTone,
  verifyKnowledgeAssertion,
  verifyKnowledgeObject,
  type KnowledgeAssertion,
  type KnowledgeConflict,
  type KnowledgeEdge,
  type KnowledgeEvidence,
  type KnowledgeObjectDetail,
} from "../../lib/knowledgeModel";
import { fmtDateTime, fmtNum, timeAgo } from "../../lib/format";
import { useAuth } from "../../auth";

const TABS = [
  { id: "resumen", label: "Resumen" },
  { id: "relaciones", label: "Relaciones" },
  { id: "hechos", label: "Hechos" },
  { id: "evidencia", label: "Evidencia" },
  { id: "historial", label: "Historial" },
  { id: "impacto", label: "Impacto" },
];

function KeyValueRow({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="flex items-start gap-3 border-b border-border-soft py-2 last:border-0">
      <span className="w-40 shrink-0 text-xs text-faint">{label}</span>
      <span className="min-w-0 flex-1 text-sm text-text">{children}</span>
    </div>
  );
}

function EdgeRow({ edge, direction }: { edge: KnowledgeEdge; direction: "in" | "out" }) {
  const otherId = direction === "out" ? edge.object_id : edge.subject_id;
  const otherName =
    direction === "out"
      ? edge.object_name || edge.object_id
      : edge.subject_name || edge.subject_id;
  return (
    <li className="flex items-center gap-3 border-b border-border-soft px-4 py-3 last:border-0">
      <ArrowsLeftRight size={14} className="shrink-0 text-faint" aria-hidden />
      <span className="min-w-0 flex-1 text-sm text-text">
        <span className="text-muted">
          {direction === "out" ? "Este objeto" : otherName}
        </span>{" "}
        <span className="font-medium">{edge.predicate}</span>{" "}
        <Link
          to={`/knowledge/objects/${otherId}`}
          className="text-accent hover:underline"
        >
          {direction === "out" ? otherName : "este objeto"}
        </Link>
      </span>
      <Badge tone="neutral" className="shrink-0">
        {edge.relationship_type}
      </Badge>
      <KnowledgeConfidenceBadge confidence={edge.confidence} compact />
    </li>
  );
}

function AssertionRow({
  assertion,
  canValidate,
  onVerify,
}: {
  assertion: KnowledgeAssertion;
  canValidate: boolean;
  onVerify: (id: string) => void;
}) {
  return (
    <li className="flex flex-col gap-1.5 border-b border-border-soft px-4 py-3 last:border-0">
      <div className="flex flex-wrap items-center gap-2">
        <span className="text-sm text-text">
          <span className="text-muted">{assertion.subject_label}</span>{" "}
          <span className="font-medium">{assertion.predicate}</span>{" "}
          {assertion.object_value ?? assertion.object_id}
        </span>
        <span className={cn("badge shrink-0", statusTone(assertion.status))}>
          {assertion.status}
        </span>
        <KnowledgeConfidenceBadge confidence={assertion.confidence} compact />
      </div>
      <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-[11px] text-faint">
        <span>{assertion.method}</span>
        <span>{assertion.evidence_count} evidencias</span>
        <span>v{assertion.version}</span>
        {assertion.updated_at && <span>actualizado {timeAgo(assertion.updated_at)}</span>}
        {canValidate && assertion.status !== "verified" && (
          <button
            type="button"
            className="text-accent hover:underline"
            onClick={() => onVerify(assertion.id)}
          >
            Verificar
          </button>
        )}
      </div>
    </li>
  );
}

function EvidenceRow({ evidence }: { evidence: KnowledgeEvidence }) {
  return (
    <li className="flex flex-col gap-1.5 border-b border-border-soft px-4 py-3 last:border-0">
      <p className="text-sm leading-relaxed text-text">
        {evidence.excerpt || "Evidencia sin extracto."}
      </p>
      <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-[11px] text-faint">
        {evidence.evidence_type && <span>{evidence.evidence_type}</span>}
        {evidence.page != null && <span>pág. {evidence.page}</span>}
        {evidence.section_path.length > 0 && (
          <span>{evidence.section_path.join(" › ")}</span>
        )}
        {evidence.strength != null && (
          <span className="mono">fuerza {Math.round(evidence.strength * 100)}%</span>
        )}
        {evidence.source_id && (
          <Link
            to={`/knowledge/sources/${evidence.source_id}`}
            className="inline-flex items-center gap-1 text-accent hover:underline"
          >
            <FileText size={11} aria-hidden />
            Ver fuente
          </Link>
        )}
        {evidence.created_at && <span>{fmtDateTime(evidence.created_at)}</span>}
      </div>
    </li>
  );
}

export default function KnowledgeObjectPage() {
  const { objectId = "" } = useParams();
  const { session } = useAuth();
  const [detail, setDetail] = useState<KnowledgeObjectDetail | null>(null);
  const [conflicts, setConflicts] = useState<KnowledgeConflict[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [notFound, setNotFound] = useState(false);
  const [actionMessage, setActionMessage] = useState("");

  const canValidate = Boolean(session?.permissions?.includes("knowledge:validate"));

  const load = useCallback(async () => {
    setLoading(true);
    setError("");
    setNotFound(false);
    try {
      const data = await fetchKnowledgeObject(objectId);
      setDetail(data);
      try {
        const all = await fetchKnowledgeConflicts("open");
        setConflicts(
          all.conflicts.filter((conflict) => conflict.object_id === objectId)
        );
      } catch {
        setConflicts([]);
      }
    } catch (err) {
      const message = err instanceof Error ? err.message : "";
      if (/404|not found|no existe/i.test(message)) setNotFound(true);
      else setError(message || "No pudimos abrir este objeto de conocimiento.");
      setDetail(null);
    } finally {
      setLoading(false);
    }
  }, [objectId]);

  useEffect(() => {
    void load();
  }, [load]);

  const object = detail?.object;
  const outgoing = useMemo(
    () => (detail?.edges ?? []).filter((edge) => edge.direction !== "in"),
    [detail]
  );
  const incoming = useMemo(
    () => (detail?.edges ?? []).filter((edge) => edge.direction === "in"),
    [detail]
  );

  const verifyObject = async () => {
    if (!object) return;
    setActionMessage("");
    try {
      await verifyKnowledgeObject(object.id);
      setActionMessage("Objeto verificado.");
      await load();
    } catch (err) {
      setActionMessage(
        err instanceof Error ? err.message : "No se pudo verificar el objeto."
      );
    }
  };

  const verifyAssertion = async (id: string) => {
    setActionMessage("");
    try {
      await verifyKnowledgeAssertion(id);
      setActionMessage("Hecho verificado.");
      await load();
    } catch (err) {
      setActionMessage(
        err instanceof Error ? err.message : "No se pudo verificar el hecho."
      );
    }
  };

  return (
    <KnowledgeLayout>
      <div className="mb-4">
        <Link
          to="/knowledge/explorer"
          className="inline-flex items-center gap-1.5 text-[13px] text-muted transition-colors duration-150 hover:text-text"
        >
          <ArrowLeft size={14} aria-hidden />
          Explorador
        </Link>
      </div>

      {loading && (
        <div className="flex flex-col gap-4" aria-busy="true">
          <Skeleton className="h-24 rounded-lg" />
          <Skeleton className="h-64 rounded-lg" />
        </div>
      )}

      {!loading && notFound && (
        <Panel>
          <EmptyState
            icon={GitBranch}
            title="Este objeto de conocimiento no existe"
            body="Puede haber sido fusionado con otro objeto o eliminado. Vuelve al explorador para encontrarlo."
            action={
              <ButtonLink to="/knowledge/explorer" variant="primary">
                Ir al explorador
              </ButtonLink>
            }
          />
        </Panel>
      )}

      {!loading && !notFound && error && (
        <div>
          <ErrorInline message={error} className="mb-0" />
          <Button className="mt-3" variant="secondary" onClick={() => void load()}>
            Reintentar
          </Button>
        </div>
      )}

      {!loading && !notFound && !error && object && detail && (
        <div className="flex flex-col gap-4">
          <Panel className="p-5">
            <div className="flex flex-wrap items-start justify-between gap-4">
              <div className="min-w-0">
                <div className="flex flex-wrap items-center gap-2">
                  <h1 className="text-h1">{object.display_name || object.name}</h1>
                  <span className="badge badge-muted">{objectTypeLabel(object.type)}</span>
                  <span className={cn("badge", statusTone(object.status))}>
                    {object.status}
                  </span>
                  {object.confidence != null && (
                    <KnowledgeConfidenceBadge confidence={object.confidence} />
                  )}
                  {conflicts.length > 0 && (
                    <span className="badge badge-pending">
                      {conflicts.length} conflicto{conflicts.length === 1 ? "" : "s"}
                    </span>
                  )}
                </div>
                <p className="prose-measure mt-2 text-sm leading-relaxed text-text">
                  {object.description ||
                    "ZENT todavía no tiene una descripción de este objeto."}
                </p>
                <div className="mt-3 flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-muted">
                  <span>{fmtNum(object.evidence_count)} evidencias</span>
                  <span>{fmtNum(object.assertion_count)} hechos</span>
                  <span>{detail.edges.length} relaciones</span>
                  {object.domain && <span>dominio {object.domain}</span>}
                  <span>actualizado {timeAgo(object.updated_at)}</span>
                </div>
              </div>
              <div className="flex flex-wrap items-center gap-2">
                {object.source_id && (
                  <ButtonLink
                    to={`/knowledge/sources/${object.source_id}`}
                    variant="secondary"
                    leadingIcon={FileText}
                  >
                    Ver fuente
                  </ButtonLink>
                )}
                {canValidate && object.status !== "verified" && (
                  <Button
                    variant="primary"
                    leadingIcon={SealCheck}
                    onClick={() => void verifyObject()}
                  >
                    Verificar objeto
                  </Button>
                )}
              </div>
            </div>
            {actionMessage && (
              <p className="mt-3 text-xs text-muted" role="status">
                {actionMessage}
              </p>
            )}
          </Panel>

          {conflicts.length > 0 && (
            <Panel className="border-warn/40 p-4">
              <p className="flex items-center gap-2 text-sm text-warn">
                <WarningCircle size={15} aria-hidden />
                Este objeto tiene {conflicts.length} conflicto(s) de conocimiento
                abiertos.
              </p>
              <Link
                to="/knowledge/health?tab=conflicts"
                className="mt-2 inline-flex items-center gap-1 text-xs text-accent hover:underline"
              >
                Revisar en Salud
                <ArrowRight size={12} aria-hidden />
              </Link>
            </Panel>
          )}

          <Tabs defaultValue="resumen">
            <TabsList>
              {TABS.map((tab) => (
                <TabsTrigger key={tab.id} value={tab.id}>
                  {tab.label}
                </TabsTrigger>
              ))}
            </TabsList>

            <TabsContent value="resumen">
              <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_minmax(0,1fr)]">
                <Panel className="p-4">
                  <p className="eyebrow mb-2">Qué sabe ZENT</p>
                  <KeyValueRow label="Tipo de conocimiento">
                    {objectTypeLabel(object.type)}
                  </KeyValueRow>
                  <KeyValueRow label="Estado">{object.status}</KeyValueRow>
                  <KeyValueRow label="Procedencia">{object.provenance || "—"}</KeyValueRow>
                  <KeyValueRow label="Confianza">
                    {object.confidence_label || "—"}
                    {object.confidence != null && (
                      <span className="mono ml-2 text-xs text-muted">
                        {Math.round(object.confidence * 100)}%
                      </span>
                    )}
                  </KeyValueRow>
                  <KeyValueRow label="Fuente de verdad">
                    {object.source_of_truth || "—"}
                  </KeyValueRow>
                  <KeyValueRow label="Autoridad">
                    {object.authority_level || "—"}
                  </KeyValueRow>
                  <KeyValueRow label="Primera vez">
                    {fmtDateTime(object.created_at)}
                  </KeyValueRow>
                  <KeyValueRow label="Última actualización">
                    {fmtDateTime(object.updated_at)}
                  </KeyValueRow>
                </Panel>
                <Panel className="p-4">
                  <p className="eyebrow mb-2">Linaje físico</p>
                  {detail.lineage.physical_refs.length === 0 ? (
                    <p className="text-sm text-muted">
                      Sin referencias físicas registradas para este objeto.
                    </p>
                  ) : (
                    <ul className="flex flex-col gap-2">
                      {detail.lineage.physical_refs.map((ref, index) => (
                        <li
                          key={`${ref.object_ref}-${index}`}
                          className="flex items-center gap-2 text-sm"
                        >
                          <LinkSimple size={13} className="text-faint" aria-hidden />
                          <span className="text-muted">{ref.system}</span>
                          <span className="text-text">{ref.object_ref}</span>
                        </li>
                      ))}
                    </ul>
                  )}
                  {detail.questions.length > 0 && (
                    <>
                      <p className="eyebrow mb-2 mt-4">Preguntas abiertas</p>
                      <ul className="flex flex-col gap-1.5">
                        {detail.questions.map((question) => (
                          <li key={question.id} className="flex items-center gap-2 text-sm">
                            <Sparkle size={12} className="text-warn" aria-hidden />
                            <span className="min-w-0 flex-1 truncate">{question.title}</span>
                            <Badge tone="neutral">{question.priority}</Badge>
                          </li>
                        ))}
                      </ul>
                    </>
                  )}
                </Panel>
              </div>
            </TabsContent>

            <TabsContent value="relaciones">
              <Panel className="overflow-hidden">
                {detail.edges.length === 0 ? (
                  <p className="p-4 text-sm text-muted">
                    Este objeto todavía no tiene relaciones registradas.
                  </p>
                ) : (
                  <ul>
                    {outgoing.map((edge) => (
                      <EdgeRow key={edge.id} edge={edge} direction="out" />
                    ))}
                    {incoming.map((edge) => (
                      <EdgeRow key={edge.id} edge={edge} direction="in" />
                    ))}
                  </ul>
                )}
              </Panel>
            </TabsContent>

            <TabsContent value="hechos">
              <Panel className="overflow-hidden">
                {detail.assertions.length === 0 ? (
                  <p className="p-4 text-sm text-muted">
                    Sin hechos asociados a este objeto.
                  </p>
                ) : (
                  <ul>
                    {detail.assertions.map((assertion) => (
                      <AssertionRow
                        key={assertion.id}
                        assertion={assertion}
                        canValidate={canValidate}
                        onVerify={(id) => void verifyAssertion(id)}
                      />
                    ))}
                  </ul>
                )}
              </Panel>
            </TabsContent>

            <TabsContent value="evidencia">
              <Panel className="overflow-hidden">
                {detail.evidence.length === 0 ? (
                  <p className="p-4 text-sm text-muted">
                    Este conocimiento no tiene evidencia localizable. Es una señal de
                    salud: ZENT no lo dará por verificado.
                  </p>
                ) : (
                  <ul>
                    {detail.evidence.map((evidence) => (
                      <EvidenceRow key={evidence.id} evidence={evidence} />
                    ))}
                  </ul>
                )}
              </Panel>
            </TabsContent>

            <TabsContent value="historial">
              <Panel className="overflow-hidden">
                {detail.versions.length === 0 ? (
                  <p className="p-4 text-sm text-muted">
                    Sin cambios registrados desde que ZENT lo conoce.
                  </p>
                ) : (
                  <ul className="flex flex-col">
                    {detail.versions.map((version) => (
                      <li
                        key={`${version.version}-${version.created_at}`}
                        className="flex items-start gap-3 border-b border-border-soft px-4 py-3 last:border-0"
                      >
                        <ClockCounterClockwise
                          size={14}
                          className="mt-0.5 shrink-0 text-faint"
                          aria-hidden
                        />
                        <div className="min-w-0 flex-1">
                          <p className="text-sm text-text">
                            v{version.version} · {version.change_kind}
                          </p>
                          {version.reason && (
                            <p className="mt-0.5 text-xs text-muted">{version.reason}</p>
                          )}
                        </div>
                        <span className="shrink-0 text-[11px] text-faint">
                          {fmtDateTime(version.created_at)}
                        </span>
                      </li>
                    ))}
                  </ul>
                )}
              </Panel>
            </TabsContent>

            <TabsContent value="impacto">
              <Panel className="overflow-hidden">
                <div className="panel-header">
                  <h2 className="text-h3">Qué depende de este objeto</h2>
                  <p className="text-xs text-muted">
                    {detail.impact.count} dependencia(s) detectadas en el grafo.
                  </p>
                </div>
                {detail.impact.dependents.length === 0 ? (
                  <p className="p-4 text-sm text-muted">
                    Ninguna otra pieza de conocimiento depende de este objeto.
                  </p>
                ) : (
                  <ul>
                    {detail.impact.dependents.map((dependent) => (
                      <li
                        key={`${dependent.kind}-${dependent.id}`}
                        className="flex items-center gap-3 border-b border-border-soft px-4 py-3 last:border-0"
                      >
                        <span className="badge badge-muted shrink-0">
                          {objectTypeLabel(dependent.type)}
                        </span>
                        <Link
                          to={`/knowledge/objects/${dependent.id}`}
                          className="min-w-0 flex-1 truncate text-sm text-text hover:underline"
                        >
                          {dependent.name}
                        </Link>
                        {dependent.via && (
                          <span className="shrink-0 text-[11px] text-faint">
                            vía {dependent.via}
                          </span>
                        )}
                      </li>
                    ))}
                  </ul>
                )}
              </Panel>
            </TabsContent>
          </Tabs>
        </div>
      )}
    </KnowledgeLayout>
  );
}
