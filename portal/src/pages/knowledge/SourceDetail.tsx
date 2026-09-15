import { ArrowsClockwise, ChatCircleDots, Files, Trash } from "@phosphor-icons/react";
import { useCallback, useEffect, useState } from "react";
import { useNavigate, useParams, useSearchParams } from "react-router-dom";
import { api } from "../../api";
import { useAuth } from "../../auth";
import { ConfirmDialog } from "../../components/ConfirmDialog";
import { KnowledgeLayout } from "../../components/KnowledgeLayout";
import { PageTabs } from "../../components/PageTabs";
import {
  Button,
  ButtonLink,
  DataTable,
  EmptyState,
  ErrorInline,
  Field,
  KeyValue,
  PageHeader,
  Panel,
  PanelHeader,
  ResultCount,
  Select,
  Skeleton,
  SuccessInline,
  type Column,
} from "../../components/ui";
import { StatusBadge } from "../../components/ui/Badge";
import { fmtDateTime, fmtNum } from "../../lib/format";
import {
  COPY,
  documentStatusLabel,
  parseSourceTab,
  SOURCE_TAB_LABEL,
  SOURCE_TABS,
  sourceStatusLabel,
  sourceTypeBlurb,
  sourceTypeLabel,
  type SourceTab,
} from "./knowledgeCopy";

type SourceDetail = {
  id: string;
  name: string;
  type: string;
  status: string;
  last_sync: string | null;
  last_error: string | null;
  document_count: number;
  error_count: number;
  knowledge_base_id?: string | null;
  config?: { managed?: boolean };
};

type KnowledgeBase = { id: string; name: string };

type SourceDocument = {
  id: number;
  external_id: string;
  document_id: string;
  status: string;
  last_seen_at: string | null;
};

type RailState = "queued" | "running" | "ready" | "failed";

/** Estado real de la fuente → rail de actividad. Sin estado conocido, rail neutro. */
const RAIL_STATE: Record<string, RailState> = {
  created: "queued",
  discovering: "running",
  ingesting: "running",
  ready: "ready",
  indexed: "ready",
  error: "failed",
};

const DOC_COLUMNS: Column<SourceDocument>[] = [
  {
    key: "external_id",
    header: "Documento",
    render: (doc) => <span className="mono text-xs text-text">{doc.external_id}</span>,
  },
  {
    key: "status",
    header: "Estado",
    render: (doc) => <span className="text-xs text-muted">{documentStatusLabel(doc.status)}</span>,
  },
  {
    key: "last_seen_at",
    header: "Visto",
    hideBelow: "md",
    render: (doc) => (
      <span className="text-xs text-muted">
        {doc.last_seen_at ? fmtDateTime(doc.last_seen_at) : "—"}
      </span>
    ),
  },
];

export default function SourceDetailPage() {
  const { sourceId } = useParams();
  const { session } = useAuth();
  const navigate = useNavigate();
  const [searchParams, setSearchParams] = useSearchParams();
  const tab = parseSourceTab(searchParams.get("tab"));
  const [source, setSource] = useState<SourceDetail | null>(null);
  const [documents, setDocuments] = useState<SourceDocument[]>([]);
  const [kbs, setKbs] = useState<KnowledgeBase[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [msg, setMsg] = useState("");
  const [syncing, setSyncing] = useState(false);
  const [confirmDelete, setConfirmDelete] = useState(false);
  const [deleting, setDeleting] = useState(false);

  const load = useCallback(async () => {
    if (!session || !sourceId) return;
    setLoading(true);
    try {
      const [sourceData, docsData, kbData] = await Promise.all([
        api<SourceDetail>(`/api/v1/sources/${sourceId}`, {
          token: session.token,
          organizationId: session.organizationId,
        }),
        api<{ documents: SourceDocument[] }>(`/api/v1/sources/${sourceId}/documents?limit=100`, {
          token: session.token,
          organizationId: session.organizationId,
        }).catch(() => ({ documents: [] as SourceDocument[] })),
        api<{ knowledge_bases: KnowledgeBase[] }>("/api/v1/knowledge-bases", {
          token: session.token,
          organizationId: session.organizationId,
        }).catch(() => ({ knowledge_bases: [] as KnowledgeBase[] })),
      ]);
      setSource(sourceData);
      setDocuments(docsData.documents || []);
      setKbs(kbData.knowledge_bases || []);
      setError("");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Error");
    } finally {
      setLoading(false);
    }
  }, [session, sourceId]);

  useEffect(() => {
    void load();
  }, [load]);

  function setTab(next: SourceTab) {
    setSearchParams(
      (prev) => {
        const nextParams = new URLSearchParams(prev);
        if (next === "resumen") nextParams.delete("tab");
        else nextParams.set("tab", next);
        return nextParams;
      },
      { replace: true },
    );
  }

  async function syncNow() {
    if (!session || !sourceId) return;
    setError("");
    setMsg("");
    setSyncing(true);
    try {
      await api(`/api/v1/sources/${sourceId}/sync`, {
        method: "POST",
        token: session.token,
        organizationId: session.organizationId,
      });
      setMsg("Sincronización encolada.");
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Error al sincronizar");
    } finally {
      setSyncing(false);
    }
  }

  async function assignKb(knowledgeBaseId: string) {
    if (!session || !sourceId || !knowledgeBaseId) return;
    setError("");
    try {
      const updated = await api<SourceDetail>(`/api/v1/sources/${sourceId}`, {
        method: "PUT",
        token: session.token,
        organizationId: session.organizationId,
        body: JSON.stringify({ knowledge_base_id: knowledgeBaseId }),
      });
      setSource(updated);
      setMsg("Colección actualizada.");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Error al agrupar");
    }
  }

  async function deleteSource() {
    if (!session || !sourceId) return;
    setDeleting(true);
    setError("");
    try {
      await api(`/api/v1/sources/${sourceId}`, {
        method: "DELETE",
        token: session.token,
        organizationId: session.organizationId,
      });
      navigate("/knowledge/sources");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Error al eliminar");
      setDeleting(false);
      setConfirmDelete(false);
    }
  }

  const tabs = SOURCE_TABS.map((id) => ({ id, label: SOURCE_TAB_LABEL[id] }));
  const managed = Boolean(source?.config?.managed);
  const docs = source?.document_count ?? 0;

  return (
    <KnowledgeLayout>
      <PageHeader
        title={source?.name || "Fuente"}
        backTo="/knowledge/sources"
        backLabel={COPY.allSources}
        meta={
          source ? (
            <>
              <span className="text-[13px] text-muted">
                {sourceTypeLabel(source.type, managed)}
              </span>
              <StatusBadge status={source.status} label={sourceStatusLabel(source.status)} />
            </>
          ) : undefined
        }
        actions={
          <>
            <ButtonLink
              to="/chat?target=knowledge"
              variant="secondary"
              size="sm"
              leadingIcon={ChatCircleDots}
            >
              {COPY.playground}
            </ButtonLink>
            <Button
              variant="ghost"
              size="sm"
              leadingIcon={Trash}
              className="text-danger"
              data-testid="source-delete"
              onClick={() => setConfirmDelete(true)}
            >
              {COPY.deleteSource}
            </Button>
          </>
        }
      />

      <div className="flex flex-col gap-4">
        <ErrorInline message={error} className="mb-0" />
        <SuccessInline message={msg} className="mb-0" />

        {loading ? (
          <div className="flex flex-col gap-4" aria-busy="true">
            <Skeleton className="h-10 w-[320px] rounded-sm" />
            <Skeleton className="h-[236px] rounded-lg" />
          </div>
        ) : !source ? null : (
          <>
            <div className="-mt-1">
              <PageTabs tabs={tabs} active={tab} onChange={(id) => setTab(id as SourceTab)} />
            </div>

            {tab === "resumen" && (
              <section data-testid="source-resumen">
                <Panel>
                  <PanelHeader title="Resumen" description={sourceTypeBlurb(source.type, managed)} />
                  <div className="panel-body flex flex-col gap-4">
                    <p
                      data-testid="source-index-copy"
                      data-state={RAIL_STATE[source.status]}
                      className="state-rail prose-measure text-[13px] leading-relaxed text-text"
                    >
                      {docs > 0 ? COPY.indexedReady : COPY.indexedEmpty}
                    </p>

                    <KeyValue
                      columns={2}
                      items={[
                        {
                          key: COPY.lastSync,
                          value: source.last_sync ? fmtDateTime(source.last_sync) : "—",
                        },
                        { key: COPY.documents, value: fmtNum(docs) },
                        {
                          key: COPY.issues,
                          value:
                            source.error_count > 0 ? (
                              <span className="text-danger">{fmtNum(source.error_count)}</span>
                            ) : (
                              "—"
                            ),
                        },
                      ]}
                    />

                    {source.last_error ? (
                      <ErrorInline message={source.last_error} className="mb-0" />
                    ) : null}

                    {kbs.length > 0 ? (
                      <Field label={COPY.collection} hint={COPY.collectionHint} className="max-w-sm">
                        <Select
                          value={source.knowledge_base_id || kbs[0]?.id || ""}
                          data-testid="source-kb"
                          aria-label={COPY.collection}
                          onChange={(e) => void assignKb(e.target.value)}
                        >
                          {kbs.map((kb) => (
                            <option key={kb.id} value={kb.id}>
                              {kb.name}
                            </option>
                          ))}
                        </Select>
                      </Field>
                    ) : null}
                  </div>
                </Panel>
              </section>
            )}

            {tab === "documentos" && (
              <section data-testid="source-documentos">
                <DataTable
                  columns={DOC_COLUMNS}
                  rows={documents}
                  rowKey={(doc) => String(doc.id)}
                  caption={`Documentos de ${source.name}`}
                  empty={
                    <EmptyState
                      icon={Files}
                      title={COPY.documentsEmpty}
                      body="Sincroniza la fuente o espera a que termine el indexado."
                    />
                  }
                  footer={
                    documents.length > 0 ? (
                      <ResultCount
                        shown={documents.length}
                        total={documents.length}
                        noun="documentos"
                      />
                    ) : undefined
                  }
                />
              </section>
            )}

            {tab === "sincronizar" && (
              <section data-testid="source-sincronizar">
                <Panel>
                  <PanelHeader
                    title="Sincronizar"
                    description="Vuelve a leer la fuente y actualiza el índice de la colección."
                  />
                  <div className="panel-body flex flex-col gap-4">
                    <KeyValue
                      columns={2}
                      items={[
                        {
                          key: COPY.lastSync,
                          value: source.last_sync
                            ? fmtDateTime(source.last_sync)
                            : COPY.neverSynced,
                        },
                        { key: COPY.documents, value: fmtNum(docs) },
                      ]}
                    />

                    {source.last_error ? (
                      <ErrorInline message={source.last_error} className="mb-0" />
                    ) : null}

                    <div className="flex flex-wrap items-center gap-3">
                      <Button
                        variant="primary"
                        leadingIcon={ArrowsClockwise}
                        loading={syncing}
                        onClick={() => void syncNow()}
                      >
                        {COPY.syncNow}
                      </Button>
                      <span className="text-xs text-faint">
                        La sincronización corre en segundo plano; los documentos se actualizan al
                        terminar.
                      </span>
                    </div>
                  </div>
                </Panel>
              </section>
            )}
          </>
        )}
      </div>

      <ConfirmDialog
        open={confirmDelete}
        title={`Eliminar ${source?.name || "fuente"}`}
        body={COPY.deleteSourceBody}
        confirmLabel={COPY.deleteSource}
        busy={deleting}
        onConfirm={() => void deleteSource()}
        onCancel={() => setConfirmDelete(false)}
      />
    </KnowledgeLayout>
  );
}
