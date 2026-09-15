import { ArrowsClockwise, ChatCircleDots, Files, Trash } from "@phosphor-icons/react";
import { useCallback, useEffect, useState } from "react";
import { Link, useNavigate, useParams, useSearchParams } from "react-router-dom";
import { api } from "../../api";
import { useAuth } from "../../auth";
import { ConfirmDialog } from "../../components/ConfirmDialog";
import { KnowledgeLayout } from "../../components/KnowledgeLayout";
import { PageTabs } from "../../components/PageTabs";
import { EmptyState, ErrorInline, PageHeader, SkeletonBlock, Spinner, SuccessInline } from "../../components/ui";
import { fmtDateTime, fmtNum } from "../../lib/format";
import {
  COPY,
  documentStatusLabel,
  parseSourceTab,
  SOURCE_TAB_LABEL,
  SOURCE_TABS,
  sourceStatusBadgeClass,
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
        actions={
          <div className="flex flex-wrap gap-2">
            <Link to="/chat?target=knowledge" className="btn btn-secondary min-h-11 text-xs">
              <ChatCircleDots size={14} aria-hidden className="mr-1" /> {COPY.playground}
            </Link>
            <Link to="/knowledge/sources" className="btn btn-secondary min-h-11 text-xs">
              {COPY.allSources}
            </Link>
            <button
              type="button"
              className="btn btn-ghost min-h-11 text-xs text-danger"
              data-testid="source-delete"
              onClick={() => setConfirmDelete(true)}
            >
              <Trash size={14} aria-hidden className="mr-1" /> {COPY.deleteSource}
            </button>
          </div>
        }
      />
      <ErrorInline message={error} />
      <SuccessInline message={msg} />

      {loading ? (
        <div className="mt-4">
          <SkeletonBlock rows={5} />
        </div>
      ) : !source ? null : (
        <>
          <PageTabs tabs={tabs} active={tab} onChange={(id) => setTab(id as SourceTab)} />

          {tab === "resumen" && (
            <section className="mt-4 space-y-3" data-testid="source-resumen">
              <div className="panel space-y-2 p-4">
                <div className="flex flex-wrap items-center gap-2">
                  <span className="text-sm text-muted">{sourceTypeLabel(source.type, managed)}</span>
                  <span className={`badge ${sourceStatusBadgeClass(source.status)}`}>
                    {sourceStatusLabel(source.status)}
                  </span>
                </div>
                <p className="text-sm text-muted">{sourceTypeBlurb(source.type, managed)}</p>
                <p className="text-sm text-text" data-testid="source-index-copy">
                  {docs > 0 ? COPY.indexedReady : COPY.indexedEmpty}
                </p>
                <dl className="grid gap-2 text-sm text-muted sm:grid-cols-2">
                  <div>
                    {COPY.lastSync}: {source.last_sync ? fmtDateTime(source.last_sync) : "—"}
                  </div>
                  <div>
                    {COPY.documents}: {fmtNum(docs)}
                  </div>
                  {source.error_count > 0 ? (
                    <div className="text-danger">
                      {COPY.issues}: {fmtNum(source.error_count)}
                    </div>
                  ) : null}
                </dl>
                {source.last_error ? <p className="text-sm text-danger">{source.last_error}</p> : null}
                {kbs.length > 0 ? (
                  <label className="block text-sm text-text">
                    {COPY.collection}
                    <select
                      className="mt-1 w-full min-h-11 rounded-md border border-border bg-soft px-3 text-sm"
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
                    </select>
                    <span className="mt-1 block text-xs text-muted">{COPY.collectionHint}</span>
                  </label>
                ) : null}
              </div>
            </section>
          )}

          {tab === "documentos" && (
            <section className="mt-4" data-testid="source-documentos">
              {documents.length === 0 ? (
                <EmptyState
                  icon={Files}
                  title={COPY.documentsEmpty}
                  body="Sincroniza la fuente o espera a que termine el indexado."
                />
              ) : (
                <div className="panel overflow-x-auto">
                  <table className="table">
                    <thead>
                      <tr>
                        <th>Documento</th>
                        <th>Estado</th>
                        <th>Visto</th>
                      </tr>
                    </thead>
                    <tbody>
                      {documents.map((doc) => (
                        <tr key={doc.id}>
                          <td className="text-sm text-text">{doc.external_id}</td>
                          <td className="text-sm text-muted">{documentStatusLabel(doc.status)}</td>
                          <td className="text-sm text-muted">{fmtDateTime(doc.last_seen_at)}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </section>
          )}

          {tab === "sincronizar" && (
            <section className="mt-4 space-y-3" data-testid="source-sincronizar">
              <div className="panel space-y-2 p-4">
                <p className="text-sm text-muted">
                  {COPY.lastSync}: {source.last_sync ? fmtDateTime(source.last_sync) : COPY.neverSynced}
                </p>
                {source.last_error ? <p className="text-sm text-danger">{source.last_error}</p> : null}
                <button
                  type="button"
                  className="btn btn-primary min-h-11"
                  disabled={syncing}
                  onClick={() => void syncNow()}
                >
                  {syncing ? <Spinner size={14} /> : <ArrowsClockwise size={14} aria-hidden />}
                  {COPY.syncNow}
                </button>
              </div>
            </section>
          )}
        </>
      )}
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
