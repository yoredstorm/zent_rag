import { ArrowsClockwise, ChatCircleDots, Code, Files, Table, Trash } from "@phosphor-icons/react";
import { useCallback, useEffect, useState } from "react";
import { useNavigate, useParams, useSearchParams } from "react-router-dom";
import { api } from "../../api";
import { useAuth } from "../../auth";
import { ConfirmDialog } from "../../components/ConfirmDialog";
import { SourceUsageWarning, useSourceUsage } from "../../components/SourceUsageWarning";
import { KnowledgeLayout } from "../../components/KnowledgeLayout";
import { PageTabs } from "../../components/PageTabs";
import {
  Button,
  ButtonLink,
  DataTable,
  EmptyState,
  ErrorInline,
  Field,
  Input,
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
import SqlRunnerModal from "../../components/SqlRunnerModal";
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

type TabularTableInfo = {
  id: string;
  name: string;
  sheet: string | null;
  row_count: number;
  column_count: number;
  header_rows: number[];
  detection_method: string;
};

type TabularPayload = {
  source_id: string;
  workbooks: {
    id: string;
    filename: string;
    sheet_count: number;
    table_count: number;
    row_count: number;
    quality_score: number | null;
    representations: Record<string, boolean> | null;
    chunk_count: number | null;
    pipeline_version: string | null;
    materialization?: {
      status?: string | null;
      tables?: { name: string; rows: number }[] | null;
      detail?: string | null;
    } | null;
  }[];
  map: string;
  tables: TabularTableInfo[];
};

type SourceTestResult = {
  matched: boolean;
  strategy?: string | null;
  confidence?: number | null;
  columns?: string[];
  rows?: string[][];
  total?: number | null;
  provenance?: {
    workbook?: string | null;
    sheet?: string | null;
    table?: string | null;
    row?: number | null;
    cell?: string | null;
    column?: string | null;
  }[];
};

type TablePreview = {
  origin: string;
  table: string | null;
  columns: string[];
  rows: unknown[][];
  count: number;
};

function asTabularPayload(payload: TabularPayload | null | undefined): TabularPayload | null {
  if (!payload || !Array.isArray(payload.workbooks)) return null;
  return {
    source_id: payload.source_id,
    workbooks: payload.workbooks.map((workbook) => ({
      ...workbook,
      chunk_count: workbook.chunk_count ?? null,
      pipeline_version: workbook.pipeline_version ?? null,
    })),
    map: typeof payload.map === "string" ? payload.map : "",
    tables: Array.isArray(payload.tables) ? payload.tables : [],
  };
}

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
  const [tabular, setTabular] = useState<TabularPayload | null>(null);
  const [testQuery, setTestQuery] = useState("");
  const [testing, setTesting] = useState(false);
  const [testResult, setTestResult] = useState<SourceTestResult | null>(null);
  const [testError, setTestError] = useState("");
  const [preview, setPreview] = useState<TablePreview | null>(null);
  const [previewLoading, setPreviewLoading] = useState(false);
  const [previewError, setPreviewError] = useState("");
  const [showSqlRunner, setShowSqlRunner] = useState(false);
  const [kbs, setKbs] = useState<KnowledgeBase[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [msg, setMsg] = useState("");
  const [syncing, setSyncing] = useState(false);
  const [confirmDelete, setConfirmDelete] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const { agents: deleteUsage, loading: deleteUsageLoading } = useSourceUsage(
    confirmDelete ? sourceId : null,
  );

  const load = useCallback(async () => {
    if (!session || !sourceId) return;
    setLoading(true);
    try {
      const [sourceData, docsData, kbData, tabularData] = await Promise.all([
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
        api<TabularPayload>(`/api/v1/sources/${sourceId}/tabular`, {
          token: session.token,
          organizationId: session.organizationId,
        }).catch(() => null),
      ]);
      setSource(sourceData);
      setDocuments(docsData.documents || []);
      setKbs(kbData.knowledge_bases || []);
      setTabular(asTabularPayload(tabularData));
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

  async function loadPreview() {
    if (!session || !sourceId) return;
    setPreviewLoading(true);
    setPreviewError("");
    try {
      const data = await api<TablePreview>(
        `/api/v1/sources/${sourceId}/table-preview?limit=25`,
        { token: session.token, organizationId: session.organizationId },
      );
      setPreview(data);
    } catch (err) {
      setPreviewError(err instanceof Error ? err.message : "Error al cargar datos");
    } finally {
      setPreviewLoading(false);
    }
  }

  async function runSourceTest() {
    if (!session || !sourceId || !testQuery.trim()) return;
    setTesting(true);
    setTestError("");
    setTestResult(null);
    try {
      const result = await api<SourceTestResult>(
        `/api/v1/sources/${sourceId}/test-query`,
        {
          method: "POST",
          token: session.token,
          organizationId: session.organizationId,
          body: JSON.stringify({ query: testQuery.trim() }),
        },
      );
      setTestResult(result);
    } catch (err) {
      setTestError(err instanceof Error ? err.message : "Error al probar");
    } finally {
      setTesting(false);
    }
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
  const canRunSql = Boolean(
    session?.permissions?.includes("*") ||
      session?.permissions?.includes("sources:sql") ||
      session?.roles?.some((role) => role === "owner" || role === "admin"),
  );

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

                {tabular && (tabular.workbooks.length > 0 || tabular.tables.length > 0) ? (
                  <Panel className="mt-4">
                    <PanelHeader
                      title="Estructura del archivo"
                      description="Hojas, tablas y columnas detectadas por la ingesta tabular."
                    />
                    <div className="panel-body flex flex-col gap-3" data-testid="source-tabular">
                      <p className="text-[13px] text-muted">
                        Excel tratado como tabla: cada fila y columna vive en la capa
                        estructurada (SQL-first), por eso la lista de documentos muestra
                        1 resumen del archivo y no una fila por registro.
                      </p>
                      {tabular.workbooks.map((workbook) => {
                        const representations = Object.entries(
                          workbook.representations || {},
                        )
                          .filter(([, enabled]) => enabled)
                          .map(([name]) => name)
                          .join(", ");
                        return (
                          <div key={workbook.id} className="text-[13px] text-text">
                            <span className="mono">{workbook.filename}</span>
                            <span className="text-muted">
                              {" "}
                              · {workbook.sheet_count} hoja(s) · {workbook.table_count} tabla(s) ·{" "}
                              {fmtNum(workbook.row_count)} filas
                              {workbook.chunk_count
                                ? ` · ${fmtNum(workbook.chunk_count)} fragmentos`
                                : ""}
                              {workbook.quality_score !== null
                                ? ` · calidad ${Math.round(workbook.quality_score * 100)}%`
                                : ""}
                              {representations ? ` · ${representations}` : ""}
                              {workbook.pipeline_version
                                ? ` · pipeline ${workbook.pipeline_version}`
                                : ""}
                            </span>
                            {workbook.materialization?.tables?.length ? (
                              <span className="ml-1 text-ok">
                                · tabla SQL:{" "}
                                {workbook.materialization.tables
                                  .map(
                                    (table) =>
                                      `${table.name} (${fmtNum(table.rows)} filas)`,
                                  )
                                  .join(", ")}
                              </span>
                            ) : workbook.materialization?.status === "skipped" ? (
                              <span className="ml-1 text-muted">
                                · tabla SQL: pendiente (sin Managed DB)
                              </span>
                            ) : null}
                          </div>
                        );
                      })}
                      {tabular.tables.length > 0 ? (
                        <ul className="space-y-1 text-[13px] text-muted">
                          {tabular.tables.slice(0, 8).map((table) => (
                            <li key={table.id}>
                              <span className="text-text">{table.name}</span>
                              {table.sheet ? ` · hoja ${table.sheet}` : ""} ·{" "}
                              {fmtNum(table.row_count)} filas · {table.column_count} columnas ·
                              header fila {table.header_rows.join(", ") || "—"}
                            </li>
                          ))}
                        </ul>
                      ) : null}
                      <div className="flex flex-wrap items-center gap-2">
                        <Button
                          variant="secondary"
                          leadingIcon={Table}
                          loading={previewLoading}
                          data-testid="source-preview-run"
                          onClick={() => void loadPreview()}
                        >
                          Ver datos
                        </Button>
                        {canRunSql ? (
                          <Button
                            variant="secondary"
                            leadingIcon={Code}
                            data-testid="source-sql-open"
                            onClick={() => setShowSqlRunner(true)}
                          >
                            Consultar SQL
                          </Button>
                        ) : null}
                        <span className="text-xs text-faint">
                          {canRunSql
                            ? "SQL read-only sobre la tabla materializada de esta fuente."
                            : "Pedí a un owner/admin para consultar por SQL."}
                        </span>
                      </div>
                      <ErrorInline message={previewError} className="mb-0" />
                      {preview ? (
                        <div className="flex flex-col gap-2" data-testid="source-preview">
                          <p className="text-xs text-faint">
                            {preview.origin === "managed_db"
                              ? `Managed DB · ${preview.table} · ${fmtNum(preview.count)} filas`
                              : preview.origin === "tabular"
                                ? `Representación estructurada · ${preview.table} · ${fmtNum(preview.count)} filas`
                                : "Sin datos materializados todavía."}
                          </p>
                          {preview.columns.length > 0 ? (
                            <div className="max-h-[320px] overflow-auto rounded-sm border border-border bg-bg/50">
                              <table className="table min-w-full text-[12.5px]">
                                <thead className="sticky top-0 bg-surface">
                                  <tr>
                                    <th className="mono w-10 text-center text-faint">#</th>
                                    {preview.columns.map((column) => (
                                      <th key={column} className="mono">
                                        {column}
                                      </th>
                                    ))}
                                  </tr>
                                </thead>
                                <tbody>
                                  {preview.rows.map((row, index) => (
                                    <tr key={index}>
                                      <td className="mono w-10 text-center text-faint">
                                        {index + 1}
                                      </td>
                                      {row.map((cell, cellIndex) => (
                                        <td
                                          key={cellIndex}
                                          className="mono max-w-[260px] truncate"
                                          title={String(cell ?? "")}
                                        >
                                          {cell === null || cell === "" ? (
                                            <span className="text-faint">NULL</span>
                                          ) : (
                                            String(cell)
                                          )}
                                        </td>
                                      ))}
                                    </tr>
                                  ))}
                                </tbody>
                              </table>
                            </div>
                          ) : null}
                        </div>
                      ) : null}
                      {tabular.map ? (
                        <details>
                          <summary className="cursor-pointer text-[13px] text-muted">
                            Ver mapa completo
                          </summary>
                          <pre className="mono mt-2 max-h-72 overflow-auto whitespace-pre-wrap text-xs text-muted">
                            {tabular.map}
                          </pre>
                        </details>
                      ) : null}
                    </div>
                  </Panel>
                ) : null}

                {tabular && tabular.tables.length > 0 ? (
                  <Panel className="mt-4">
                    <PanelHeader
                      title="Probar esta fuente"
                      description="Consulta exacta sobre la tabla (sin LLM): posición, longitud, valor o listas."
                    />
                    <div className="panel-body flex flex-col gap-3" data-testid="source-test">
                      <div className="flex flex-wrap items-center gap-2">
                        <Input
                          value={testQuery}
                          data-testid="source-test-query"
                          aria-label="Consulta de prueba"
                          placeholder="¿Cuál es la posición de Carrier Code?"
                          onChange={(e) => setTestQuery(e.target.value)}
                          onKeyDown={(e) => {
                            if (e.key === "Enter") void runSourceTest();
                          }}
                        />
                        <Button
                          variant="secondary"
                          loading={testing}
                          disabled={!testQuery.trim()}
                          data-testid="source-test-run"
                          onClick={() => void runSourceTest()}
                        >
                          Probar
                        </Button>
                      </div>
                      <ErrorInline message={testError} className="mb-0" />
                      {testResult && !testResult.matched ? (
                        <p className="text-sm text-muted">
                          Sin coincidencia exacta para esa pregunta. Prueba con el nombre de un
                          campo o pregunta al agente (búsqueda semántica).
                        </p>
                      ) : null}
                      {testResult?.matched ? (
                        <div className="flex flex-col gap-2" data-testid="source-test-result">
                          <div className="text-[13px] text-text">
                            <span className="text-muted">
                              {(testResult.columns || []).join(" · ")}
                              {testResult.total && testResult.total > 1
                                ? ` (${fmtNum(testResult.total)} coincidencias)`
                                : ""}
                            </span>
                          </div>
                          <ul className="space-y-1 text-[13px]">
                            {(testResult.rows || []).slice(0, 8).map((row, index) => (
                              <li key={index}>
                                <span className="text-text">{row[0]}</span>
                                {row.length > 1 ? (
                                  <span className="text-muted"> · {row[1]}</span>
                                ) : null}
                              </li>
                            ))}
                          </ul>
                          {testResult.provenance?.[0] ? (
                            <p className="text-xs text-faint">
                              {testResult.provenance[0].workbook}
                              {testResult.provenance[0].sheet
                                ? ` · hoja ${testResult.provenance[0].sheet}`
                                : ""}
                              {testResult.provenance[0].row
                                ? ` · fila ${testResult.provenance[0].row}`
                                : ""}
                              {testResult.provenance[0].cell
                                ? ` · celda ${testResult.provenance[0].cell}`
                                : ""}
                              {testResult.strategy ? ` · ${testResult.strategy}` : ""}
                            </p>
                          ) : null}
                        </div>
                      ) : null}
                    </div>
                  </Panel>
                ) : null}
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
        body={
          <>
            {COPY.deleteSourceBody}
            <SourceUsageWarning agents={deleteUsage} loading={deleteUsageLoading} />
          </>
        }
        confirmLabel={COPY.deleteSource}
        busy={deleting}
        onConfirm={() => void deleteSource()}
        onCancel={() => setConfirmDelete(false)}
      />

      {showSqlRunner ? (
        <SqlRunnerModal
          sql={
            preview?.table
              ? `SELECT *\nFROM ${preview.table}\nLIMIT 20;`
              : "SELECT *\nFROM zent_tabla\nLIMIT 20;"
          }
          endpoint={`/api/v1/sources/${sourceId}/sql`}
          title="Consultar la tabla materializada"
          hint="Solo SELECT · solo las tablas de esta fuente · read-only"
          onClose={() => setShowSqlRunner(false)}
        />
      ) : null}
    </KnowledgeLayout>
  );
}
