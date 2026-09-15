import {
  BookOpen,
  CaretDown,
  Check,
  CheckCircle,
  CursorClick,
  MagnifyingGlass,
  Plus,
  Prohibit,
  Question,
  WarningCircle,
  X,
  type Icon,
} from "@phosphor-icons/react";
import { useCallback, useEffect, useMemo, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { api } from "../../api";
import { useAuth } from "../../auth";
import {
  Badge,
  Button,
  ButtonLink,
  CodeBlock,
  EmptyState,
  ErrorInline,
  Field,
  InfoInline,
  Input,
  KeyValue,
  PageHeader,
  Panel,
  PanelHeader,
  Select,
  Skeleton,
  SplitPane,
  Textarea,
  type Tone,
} from "../../components/ui";
import { KnowledgeLayout } from "../../components/KnowledgeLayout";
import { KNOWLEDGE_HEADINGS } from "../../lib/knowledgeNav";
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

const GROUP_META: Record<string, { label: string; tone: Tone; icon: Icon }> = {
  high: { label: "Alta confianza", tone: "ok", icon: CheckCircle },
  needs_review: { label: "Necesita revisión", tone: "warn", icon: WarningCircle },
  unknown: { label: "Desconocido", tone: "neutral", icon: Question },
  approved: { label: "Aprobado", tone: "ok", icon: Check },
};

const PHASE_LABELS: Record<string, string> = {
  QUEUED: "en cola",
  SCANNING: "escaneando",
  PROFILING: "perfilando",
  INFERRING: "infiriendo",
  WAITING_REVIEW: "esperando revisión",
  COMPLETED: "completada",
  PARTIAL: "parcial",
  FAILED: "falló",
  CANCELLED: "cancelada",
};

const ROLE_LABELS: Record<string, string> = {
  IDENTIFIER: "Identificador",
  DESCRIPTION: "Descripción",
  MEASURE: "Medida",
  DATE: "Fecha",
  STATUS: "Estado",
  CATEGORY: "Categoría",
  RELATIONSHIP: "Relación",
  UNKNOWN: "Sin definir",
};

function GroupBadge({ group }: { group: string }) {
  const meta = GROUP_META[group];
  if (!meta) return <Badge tone="neutral">{groupLabel(group)}</Badge>;
  const IconEl = meta.icon;
  return (
    <Badge tone={meta.tone} icon={IconEl}>
      {meta.label}
    </Badge>
  );
}

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
  const samples = selected
    ? detail?.columns.find((c) => c.id === selected.column.id)?.samples || []
    : [];

  return (
    <KnowledgeLayout>
      <div data-testid="studio-page">
      <PageHeader
        title={KNOWLEDGE_HEADINGS.understanding}
        subtitle="Zent mapea nombres físicos a conceptos de negocio. Nada se auto-aprueba."
        actions={
          <>
            <ButtonLink to="/knowledge/add" size="sm" variant="secondary" leadingIcon={Plus}>
              Añade fuente
            </ButtonLink>
            <Button
              size="sm"
              variant={lexiconOpen ? "primary" : "secondary"}
              leadingIcon={BookOpen}
              aria-expanded={lexiconOpen}
              onClick={() => setLexiconOpen((v) => !v)}
            >
              Léxico
            </Button>
          </>
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
          body="Conectá una base o subí un archivo. Luego confirmá qué significa cada campo."
          hint="El mapeo se hace campo por campo: solo lo que confirmás alimenta las respuestas."
          action={
            <ButtonLink to="/knowledge/add" variant="primary" leadingIcon={Plus}>
              Añade fuente
            </ButtonLink>
          }
        />
      ) : (
        <div data-testid="studio-layout">
          <SplitPane
            secondaryWidth={380}
            primary={
              <div className="flex min-w-0 flex-col gap-4 lg:flex-row lg:items-start">
                <Panel className="p-4 lg:w-[236px] lg:shrink-0">
                  <Field label="Fuente" id="studio-source" hint="El descubrimiento corre por fuente.">
                    <Select
                      value={sourceId}
                      onChange={(e) => {
                        setSourceId(e.target.value);
                        setSearchParams({ source_id: e.target.value });
                      }}
                    >
                      {sources.map((s) => (
                        <option key={s.id} value={s.id}>
                          {s.engine} · {PHASE_LABELS[s.phase] ?? s.phase}
                        </option>
                      ))}
                    </Select>
                  </Field>

                  <div className="mt-4">
                    <Field label="Buscar" id="studio-search" hint="Por tabla, columna o campo.">
                      <Input
                        icon={MagnifyingGlass}
                        value={q}
                        onChange={(e) => setQ(e.target.value)}
                        placeholder="tabla, columna, campo"
                        data-testid="studio-search"
                      />
                    </Field>
                  </div>

                  <dl className="mt-4 grid grid-cols-2 gap-3 border-t border-border pt-4">
                    <div className="min-w-0">
                      <dt className="eyebrow">Campos</dt>
                      <dd className="mono mt-0.5 text-sm text-text">
                        {tree ? tree.total : "—"}
                      </dd>
                    </div>
                    <div className="min-w-0">
                      <dt className="eyebrow">Alta confianza</dt>
                      <dd className="mono mt-0.5 text-sm text-accent">{highIds.length}</dd>
                    </div>
                  </dl>
                </Panel>

                <Panel className="min-w-0 flex-1">
                  <PanelHeader
                    title="Campos"
                    description="Agrupados por confianza del mapeo inferido."
                    actions={
                      tree ? (
                        <span className="text-xs text-faint tabular-nums">
                          {tree.total} en total
                        </span>
                      ) : undefined
                    }
                  />
                  <div className="p-4">
                    {loading ? (
                      <div className="flex flex-col gap-2" aria-hidden>
                        <Skeleton className="h-9 rounded-sm" />
                        <Skeleton className="h-9 rounded-sm" />
                        <Skeleton className="h-9 rounded-sm" />
                        <Skeleton className="h-9 rounded-sm" />
                      </div>
                    ) : (
                      <>
                        {highIds.length > 0 && (
                          <div className="mb-4 flex flex-wrap items-center gap-2 rounded-md border border-accent-line bg-accent-soft/50 p-2.5">
                            <span className="text-[13px] text-text">
                              {highIds.length} campos de alta confianza
                            </span>
                            <span className="flex flex-1 items-center justify-end gap-2">
                              <Button
                                size="sm"
                                variant="ghost"
                                data-testid="studio-bulk-select"
                                onClick={() => setSelectedIds(highIds)}
                              >
                                Revisar lista
                              </Button>
                              <Button
                                size="sm"
                                variant="primary"
                                disabled={!selectedIds.length || busy}
                                onClick={bulkApprove}
                                data-testid="studio-bulk-approve"
                              >
                                Aprobar seleccionados ({selectedIds.length})
                              </Button>
                            </span>
                          </div>
                        )}
                        {GROUP_ORDER.map((g) => {
                          const items = groups[g] || [];
                          // Solo grupos con contenido: una lista de "Ninguno" no aporta.
                          if (items.length === 0) return null;
                          return (
                            <div key={g} className="mb-5 last:mb-0">
                              <div className="mb-1.5 flex items-center gap-2">
                                <p className="eyebrow">{groupLabel(g)}</p>
                                <span className="mono text-[11px] text-faint">{items.length}</span>
                              </div>
                              <div className="flex flex-col gap-0.5">
                                {items.map((item) => {
                                  const isSelected = selected?.column.id === item.column.id;
                                  return (
                                    <button
                                      key={item.column.id}
                                      type="button"
                                      aria-pressed={isSelected}
                                      className={`flex w-full items-center justify-between gap-3 rounded-sm px-3 py-2 text-left text-sm transition-colors duration-120 ${
                                        isSelected ? "bg-accent-soft text-text" : "hover:bg-soft"
                                      }`}
                                      onClick={() => pick(item)}
                                      data-testid={`studio-col-${item.column.column_name}`}
                                    >
                                      <span className="flex min-w-0 items-center gap-2">
                                        <span className="mono truncate text-[13px] text-text">
                                          {item.column.column_name}
                                        </span>
                                        <span className="truncate text-xs text-faint">
                                          {item.table_name}
                                        </span>
                                        {item.field && (
                                          <span className="truncate text-[13px]">
                                            {item.field.name}
                                          </span>
                                        )}
                                      </span>
                                      <span className="flex shrink-0 items-center gap-2">
                                        {impactHint(item.field?.role) && (
                                          <Badge tone="warn">{impactHint(item.field?.role)}</Badge>
                                        )}
                                        <GroupBadge group={item.group} />
                                      </span>
                                    </button>
                                  );
                                })}
                              </div>
                            </div>
                          );
                        })}
                        {tree && tree.total === 0 && (
                          <EmptyState
                            compact
                            icon={MagnifyingGlass}
                            title="Sin campos que revisar"
                            body="Cuando una fuente termine de escanear, sus campos aparecen acá agrupados por confianza."
                          />
                        )}
                      </>
                    )}
                  </div>
                </Panel>
              </div>
            }
            secondary={
              <div data-testid="studio-detail">
                <Panel>
                  <PanelHeader
                    title={selected ? selected.column.column_name : "Detalle"}
                    description={
                      selected
                        ? `${selected.qualified_name}.${selected.column.column_name}`
                        : "Elegí un campo de la lista para revisar su mapeo."
                    }
                    actions={selected ? <GroupBadge group={selected.group} /> : undefined}
                  />
                  <div className="p-4">
                    {!selected ? (
                      <EmptyState
                        compact
                        icon={CursorClick}
                        title="Ningún campo seleccionado"
                        body="Elegí un campo para ver de dónde sale su significado y confirmarlo."
                      />
                    ) : (
                      <>
                        {selected.template && (
                          <InfoInline className="mb-4">
                            Plantilla {selected.template.entity}. Puedes ignorarla y crear una
                            entidad propia.
                          </InfoInline>
                        )}

                        <p className="eyebrow">Físico</p>
                        <KeyValue
                          className="mt-2"
                          items={[
                            {
                              key: "Origen",
                              value: `${selected.qualified_name}.${selected.column.column_name}`,
                              mono: true,
                            },
                            { key: "Tipo de dato", value: selected.column.data_type, mono: true },
                            ...(detail
                              ? [
                                  {
                                    key: "Muestras",
                                    value:
                                      samples.length > 0 ? samples.join(", ") : "sin muestras",
                                    mono: true,
                                  },
                                ]
                              : []),
                          ]}
                        />

                        <p className="eyebrow mt-4">Negocio</p>
                        <KeyValue
                          className="mt-2"
                          columns={2}
                          items={[
                            { key: "Entidad", value: selected.entity?.name || "Sin entidad" },
                            { key: "Campo", value: selected.field?.name || "Sin campo" },
                            {
                              key: "Rol",
                              value:
                                ROLE_LABELS[selected.field?.role ?? ""] ??
                                selected.field?.role ??
                                "Sin definir",
                            },
                          ]}
                        />

                        {selected.field?.mapping_type &&
                          ["TRANSFORMED", "DERIVED"].includes(selected.field.mapping_type) && (
                            <p className="mt-2 text-xs text-faint">
                              Mapeo {selected.field.mapping_type}: todavía no se edita desde este
                              panel.
                            </p>
                          )}

                        {selected.field && (
                          <div className="mt-4 flex flex-wrap gap-2">
                            <Button
                              size="sm"
                              variant="primary"
                              leadingIcon={Check}
                              disabled={busy}
                              loading={busy}
                              onClick={() => review("confirm")}
                              data-testid="studio-confirm"
                            >
                              Confirmar
                            </Button>
                            <Button
                              size="sm"
                              variant="secondary"
                              leadingIcon={X}
                              disabled={busy}
                              onClick={() => review("reject")}
                            >
                              Rechazar
                            </Button>
                            <Button
                              size="sm"
                              variant="ghost"
                              leadingIcon={Prohibit}
                              disabled={busy}
                              onClick={() => review("ignore")}
                            >
                              Ignorar
                            </Button>
                          </div>
                        )}

                        <FreeTextDraft columnId={selected.column.id} onCreated={loadTree} auth={auth} />
                        <EnumEditor
                          columnId={selected.column.id}
                          meanings={enumMeanings}
                          setMeanings={setEnumMeanings}
                          onSave={saveEnum}
                          auth={auth}
                        />

                        <div className="mt-4">
                          <Button
                            size="sm"
                            variant="ghost"
                            trailingIcon={CaretDown}
                            aria-expanded={advanced}
                            onClick={() => setAdvanced((v) => !v)}
                          >
                            Avanzado
                          </Button>
                          {advanced && selected.field && (
                            <CodeBlock
                              className="mt-2"
                              code={JSON.stringify(selected.field.signal_scores || {}, null, 2)}
                              language="json"
                              maxHeight={240}
                            />
                          )}
                        </div>

                        <div className="mt-5 border-t border-border pt-4">
                          <div className="flex items-center gap-2">
                            <h3 className="text-h3">SQL de prueba</h3>
                            <Badge tone="warn">Borrador</Badge>
                          </div>
                          <div className="mt-3 flex flex-col gap-3">
                            <Field label="Pregunta">
                              <Input
                                value={draftQuestion}
                                onChange={(e) => setDraftQuestion(e.target.value)}
                                placeholder="¿Cuánto stock hay del ibuprofeno?"
                              />
                            </Field>
                            <Field label="SQL">
                              <Textarea
                                rows={2}
                                value={draftSql}
                                onChange={(e) => setDraftSql(e.target.value)}
                                placeholder="SELECT …"
                                className="font-mono text-xs"
                              />
                            </Field>
                            <div className="flex justify-end">
                              <Button
                                size="sm"
                                variant="secondary"
                                disabled={!draftQuestion || !draftSql}
                                onClick={saveDraft}
                              >
                                Guardar borrador
                              </Button>
                            </div>
                          </div>
                        </div>
                      </>
                    )}
                  </div>
                </Panel>
              </div>
            }
          />
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
    <div className="mt-4 border-t border-border pt-4" data-testid="studio-enums">
      <p className="eyebrow">Valores del enum</p>
      <p className="mt-1 text-xs text-faint">Documentá cada valor uno por uno.</p>
      <div className="mt-3 flex flex-col gap-2">
        {values.map((v) => (
          <div key={v.id} className="flex items-center gap-2">
            <span className="mono w-24 shrink-0 truncate text-xs text-text">{v.value}</span>
            <Input
              className="min-w-0 flex-1"
              aria-label={`Significado de ${v.value}`}
              placeholder={v.documented_meaning || "significado"}
              value={meanings[v.id] ?? ""}
              onChange={(e) => setMeanings({ ...meanings, [v.id]: e.target.value })}
            />
            <Button
              size="sm"
              variant="secondary"
              aria-label={`Guardar significado de ${v.value}`}
              onClick={() => onSave(v.id)}
            >
              Guardar
            </Button>
          </div>
        ))}
      </div>
    </div>
  );
}
