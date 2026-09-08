import { Check, MagnifyingGlass, Prohibit, X } from "@phosphor-icons/react";
import { useCallback, useEffect, useMemo, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { api } from "../../api";
import { useAuth } from "../../auth";
import { EmptyState, ErrorInline, PageHeader, SkeletonBlock, StatusBadge } from "../../components/ui";
import { KnowledgeLayout } from "../../components/KnowledgeLayout";
import { FreeTextDraft, GROUP_ORDER, LexiconPanel, groupLabel, impactHint } from "./studio/panels";

type CatalogSource = { id: string; engine: string; phase: string };

type StudioItem = {
  table_id: string;
  table_name: string;
  qualified_name: string;
  column: {
    id: string;
    column_name: string;
    data_type: string;
    is_sensitive?: boolean;
    sample_disabled?: boolean;
  };
  field: {
    id: string;
    name: string;
    role: string;
    status: string;
    confidence: string;
    mapping_type?: string;
    signal_scores?: Record<string, number>;
    synonyms?: string[];
  } | null;
  entity: { id: string; name: string } | null;
  suggestion: { id: string; confidence: string; payload?: Record<string, unknown> } | null;
  group: "high" | "needs_review" | "unknown" | "approved";
  template?: { entity: string; slots: { slot: string; role: string }[] } | null;
};

type StudioTree = {
  source: CatalogSource;
  groups: Record<string, StudioItem[]>;
  total: number;
  high_confidence_ids: string[];
};

type TableDetail = {
  table: { table_name: string; qualified_name: string };
  columns: Array<StudioItem["column"] & { samples: string[]; field: StudioItem["field"]; suggestion: StudioItem["suggestion"] }>;
  coming_later: string[];
};

export default function KnowledgeUnderstandingPage() {
  const { session } = useAuth();
  const [params, setSearchParams] = useSearchParams();
  const [sources, setSources] = useState<CatalogSource[]>([]);
  const [sourceId, setSourceId] = useState(params.get("source_id") || "");
  const [tree, setTree] = useState<StudioTree | null>(null);
  const [q, setQ] = useState("");
  const [selected, setSelected] = useState<StudioItem | null>(null);
  const [detail, setDetail] = useState<TableDetail | null>(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);
  const [lexiconOpen, setLexiconOpen] = useState(false);
  const [advanced, setAdvanced] = useState(false);
  const [selectedIds, setSelectedIds] = useState<string[]>([]);
  const [enumMeanings, setEnumMeanings] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState(false);
  const [draftSql, setDraftSql] = useState("");
  const [draftQuestion, setDraftQuestion] = useState("");

  const auth = useMemo(
    () =>
      session
        ? { token: session.token, organizationId: session.organizationId }
        : undefined,
    [session]
  );

  const loadSources = useCallback(() => {
    if (!session || !auth) return;
    api<CatalogSource[]>("/api/v1/catalog/sources", auth)
      .then((rows) => {
        setSources(rows);
        if (!sourceId && rows[0]) {
          setSourceId(rows[0].id);
          setSearchParams({ source_id: rows[0].id });
        }
      })
      .catch((e) => setError(String(e)))
      .finally(() => {
        if (!sourceId) setLoading(false);
      });
  }, [session, auth, sourceId, setSearchParams]);

  const loadTree = useCallback(() => {
    if (!session || !auth || !sourceId) {
      setLoading(false);
      return;
    }
    setLoading(true);
    const qs = q.trim() ? `&q=${encodeURIComponent(q)}` : "";
    api<StudioTree>(`/api/v1/catalog/studio/${sourceId}?limit=80${qs}`, auth)
      .then(setTree)
      .catch((e) => setError(String(e)))
      .finally(() => setLoading(false));
  }, [session, auth, sourceId, q]);

  useEffect(() => loadSources(), [loadSources]);
  useEffect(() => loadTree(), [loadTree]);

  const pick = async (item: StudioItem) => {
    setSelected(item);
    try {
      const d = await api<TableDetail>(`/api/v1/catalog/studio/tables/${item.table_id}`, auth);
      setDetail(d);
    } catch (e) {
      setError(String(e));
    }
  };

  const review = async (action: "confirm" | "change" | "reject" | "ignore") => {
    if (!selected?.field) return;
    setBusy(true);
    try {
      await api(`/api/v1/catalog/studio/fields/${selected.field.id}/review`, {
        method: "POST",
        body: JSON.stringify({
          action,
          payload: { suggestion_id: selected.suggestion?.id },
        }),
        ...auth,
      });
      loadTree();
    } catch (e) {
      setError(String(e));
    } finally {
      setBusy(false);
    }
  };

  const bulkApprove = async () => {
    if (!selectedIds.length) return;
    setBusy(true);
    try {
      await api("/api/v1/catalog/studio/bulk", {
        method: "POST",
        body: JSON.stringify({ suggestion_ids: selectedIds, action: "approve" }),
        ...auth,
      });
      setSelectedIds([]);
      loadTree();
    } catch (e) {
      setError(String(e));
    } finally {
      setBusy(false);
    }
  };

  const saveEnum = async (valueId: string) => {
    const meaning = enumMeanings[valueId];
    if (!meaning) return;
    try {
      await api(`/api/v1/catalog/enums/${valueId}`, {
        method: "PUT",
        body: JSON.stringify({ meaning }),
        ...auth,
      });
      loadTree();
    } catch (e) {
      setError(String(e));
    }
  };

  const saveDraft = async () => {
    if (!draftQuestion || !draftSql) return;
    try {
      await api("/api/v1/catalog/studio/verified-query-draft", {
        method: "POST",
        body: JSON.stringify({ question: draftQuestion, sql: draftSql }),
        ...auth,
      });
      setDraftQuestion("");
      setDraftSql("");
    } catch (e) {
      setError(String(e));
    }
  };

  const groups = tree?.groups || { high: [], needs_review: [], unknown: [], approved: [] };
  const highIds = useMemo(() => tree?.high_confidence_ids || [], [tree]);

  return (
    <KnowledgeLayout>
      <div data-testid="studio-page">
      <PageHeader
        title="Entendimiento"
        subtitle="Zent mapea nombres físicos a conceptos de negocio. Nada se auto-aprueba."
        actions={
          <div className="flex gap-2">
            <Link className="btn btn-sm" to="/knowledge/add">
              Añade fuente
            </Link>
            <button type="button" className="btn btn-sm" onClick={() => setLexiconOpen((v) => !v)}>
              Léxico
            </button>
          </div>
        }
      />
      {error && <ErrorInline message={error} />}
      {lexiconOpen && (
        <div className="mb-4">
          <LexiconPanel onClose={() => setLexiconOpen(false)} auth={auth} />
        </div>
      )}
      {!sourceId && !loading ? (
        <EmptyState
          icon={MagnifyingGlass}
          title="Todavía no hay catálogo"
          body="Conecta una base o sube un archivo. Luego confirma qué significa cada campo."
        />
      ) : (
        <div className="grid gap-3 lg:grid-cols-[220px_1fr_280px]" data-testid="studio-layout">
          <aside className="card p-3">
            <label className="text-xs text-zinc-500" htmlFor="studio-source">Fuente</label>
            <select
              id="studio-source"
              className="input mt-1 w-full"
              value={sourceId}
              onChange={(e) => {
                setSourceId(e.target.value);
                setSearchParams({ source_id: e.target.value });
              }}
            >
              {sources.map((s) => (
                <option key={s.id} value={s.id}>
                  {s.engine} · {s.phase}
                </option>
              ))}
            </select>
            <label className="mt-3 block text-xs text-zinc-500" htmlFor="studio-search">Buscar</label>
            <input
              id="studio-search"
              className="input mt-1 w-full"
              value={q}
              onChange={(e) => setQ(e.target.value)}
              placeholder="tabla, columna, campo"
              data-testid="studio-search"
            />
          </aside>
          <section className="card p-3">
            {loading ? (
              <SkeletonBlock rows={6} />
            ) : (
              <>
                {highIds.length > 0 && (
                  <div className="mb-3 flex items-center justify-between gap-2 rounded bg-indigo-50 p-2 text-sm">
                    <span>{highIds.length} de alta confianza</span>
                    <button
                      type="button"
                      className="btn btn-sm"
                      data-testid="studio-bulk-select"
                      onClick={() => setSelectedIds(highIds)}
                    >
                      Revisar lista
                    </button>
                    <button
                      type="button"
                      className="btn btn-sm btn-primary"
                      disabled={!selectedIds.length || busy}
                      onClick={bulkApprove}
                      data-testid="studio-bulk-approve"
                    >
                      Aprobar seleccionados ({selectedIds.length})
                    </button>
                  </div>
                )}
                {GROUP_ORDER.map((g) => (
                  <div key={g} className="mb-4">
                    <h3 className="mb-2 text-xs font-semibold uppercase tracking-wide text-zinc-500">
                      {groupLabel(g)}
                    </h3>
                    <div className="space-y-1">
                      {(groups[g] || []).map((item) => (
                        <button
                          key={item.column.id}
                          type="button"
                          className={`flex w-full items-center justify-between rounded px-2 py-2 text-left text-sm hover:bg-zinc-50 ${selected?.column.id === item.column.id ? "bg-indigo-50" : ""}`}
                          onClick={() => pick(item)}
                          data-testid={`studio-col-${item.column.column_name}`}
                        >
                          <span>
                            <span className="font-mono">{item.column.column_name}</span>
                            <span className="ml-2 text-zinc-400">{item.table_name}</span>
                            {item.field && <span className="ml-2">{item.field.name}</span>}
                          </span>
                          <span className="flex items-center gap-2">
                            {impactHint(item.field?.role) && (
                              <span className="text-[10px] text-amber-700">{impactHint(item.field?.role)}</span>
                            )}
                            <StatusBadge status={item.group} />
                          </span>
                        </button>
                      ))}
                      {(groups[g] || []).length === 0 && (
                        <p className="text-xs text-zinc-400">Ninguno</p>
                      )}
                    </div>
                  </div>
                ))}
              </>
            )}
          </section>
          <aside className="card p-3" data-testid="studio-detail">
            {!selected ? (
              <p className="text-sm text-zinc-500">Elige un campo para confirmar su significado.</p>
            ) : (
              <>
                {selected.template && (
                  <div className="mb-2 rounded bg-zinc-50 p-2 text-xs">
                    Plantilla {selected.template.entity}. Puedes ignorarla y crear una entidad propia.
                  </div>
                )}
                <h3 className="text-sm font-semibold">Físico</h3>
                <p className="text-sm">
                  {selected.qualified_name}.{selected.column.column_name} · {selected.column.data_type}
                </p>
                {detail && (
                  <p className="mt-1 text-xs text-zinc-500">
                    Muestras:{" "}
                    {(detail.columns.find((c) => c.id === selected.column.id)?.samples || []).join(", ") || "sin muestras"}
                  </p>
                )}
                <h3 className="mt-3 text-sm font-semibold">Negocio</h3>
                <p className="text-sm">
                  {selected.entity?.name || "Sin entidad"} · {selected.field?.name || "sin campo"} · {selected.field?.role || "UNKNOWN"}
                </p>
                {selected.field?.mapping_type && ["TRANSFORMED", "DERIVED"].includes(selected.field.mapping_type) && (
                  <p className="mt-1 text-xs text-zinc-400">TRANSFORMED/DERIVED — Coming later</p>
                )}
                {selected.field && (
                  <div className="mt-3 flex flex-wrap gap-2">
                    <button type="button" className="btn btn-sm btn-primary" disabled={busy} onClick={() => review("confirm")} data-testid="studio-confirm">
                      <Check size={14} /> Confirmar
                    </button>
                    <button type="button" className="btn btn-sm" disabled={busy} onClick={() => review("reject")}>
                      <X size={14} /> Rechazar
                    </button>
                    <button type="button" className="btn btn-sm" disabled={busy} onClick={() => review("ignore")}>
                      <Prohibit size={14} /> Ignorar
                    </button>
                  </div>
                )}
                <FreeTextDraft columnId={selected.column.id} onCreated={loadTree} auth={auth} />
                <EnumEditor columnId={selected.column.id} meanings={enumMeanings} setMeanings={setEnumMeanings} onSave={saveEnum} auth={auth} />
                <button type="button" className="btn btn-sm mt-3" onClick={() => setAdvanced((v) => !v)}>
                  Avanzado
                </button>
                {advanced && selected.field && (
                  <pre className="mt-2 overflow-auto text-[10px] text-zinc-500">
                    {JSON.stringify(selected.field.signal_scores || {}, null, 2)}
                  </pre>
                )}
                <div className="mt-4 border-t pt-3">
                  <h3 className="text-sm font-semibold">SQL de prueba (DRAFT)</h3>
                  <input
                    className="input mt-1 w-full"
                    placeholder="Pregunta"
                    value={draftQuestion}
                    onChange={(e) => setDraftQuestion(e.target.value)}
                  />
                  <textarea
                    className="input mt-1 w-full"
                    rows={2}
                    placeholder="SELECT …"
                    value={draftSql}
                    onChange={(e) => setDraftSql(e.target.value)}
                  />
                  <button type="button" className="btn btn-sm mt-2" onClick={saveDraft} disabled={!draftQuestion || !draftSql}>
                    Guardar como DRAFT
                  </button>
                </div>
              </>
            )}
          </aside>
        </div>
      )}
      </div>
    </KnowledgeLayout>
  );
}

function EnumEditor({
  columnId,
  meanings,
  setMeanings,
  onSave,
  auth,
}: {
  columnId: string;
  meanings: Record<string, string>;
  setMeanings: (v: Record<string, string>) => void;
  onSave: (id: string) => void;
  auth?: { token?: string; organizationId: string };
}) {
  const [values, setValues] = useState<Array<{ id: string; value: string; documented_meaning: string | null }>>([]);
  useEffect(() => {
    api<Array<{ column_id: string; values: Array<{ id: string; value: string; documented_meaning: string | null }> }>>(
      "/api/v1/catalog/enums",
      auth
    )
      .then((rows) => {
        const hit = rows.find((r) => r.column_id === columnId);
        setValues(hit?.values || []);
      })
      .catch(() => setValues([]));
  }, [columnId, auth]);
  if (!values.length) return null;
  return (
    <div className="mt-3" data-testid="studio-enums">
      <h4 className="text-xs font-semibold">Valores (uno por uno)</h4>
      {values.map((v) => (
        <div key={v.id} className="mt-1 flex gap-1">
          <span className="font-mono text-xs">{v.value}</span>
          <input
            className="input flex-1"
            placeholder={v.documented_meaning || "significado"}
            value={meanings[v.id] ?? ""}
            onChange={(e) => setMeanings({ ...meanings, [v.id]: e.target.value })}
          />
          <button type="button" className="btn btn-sm" onClick={() => onSave(v.id)}>
            Guardar
          </button>
        </div>
      ))}
    </div>
  );
}
