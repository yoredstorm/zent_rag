import {
  CheckCircle,
  Clock,
  FileText,
  Minus,
  Question,
  ShieldCheck,
  XCircle,
  type Icon,
} from "@phosphor-icons/react";
import { useEffect, useMemo, useState } from "react";
import { api } from "../api";
import { useAuth } from "../auth";
import {
  Badge,
  Button,
  ConfirmDialog,
  DataTable,
  Drawer,
  EmptyState,
  ErrorInline,
  Field,
  FormActions,
  InfoInline,
  KeyValue,
  Menu,
  MenuItem,
  MenuLabel,
  Metric,
  MetricGrid,
  PageHeader,
  Pagination,
  Panel,
  PanelHeader,
  ResultCount,
  SectionHeader,
  Select,
  SkeletonBlock,
  SuccessInline,
  WarningInline,
  menuItemClass,
  menuLabelClass,
  type Column,
  type SortState,
  type Tone,
} from "../components/ui";
import { fmtDateTime } from "../lib/format";

type Report = { id: string; report_type: string; period_start: string; period_end: string; format: string; size_bytes: number; integrity_hash: string; prev_hash: string | null; created_at: string };
type Control = { framework: string; control_id: string; title: string; category: string; required_evidence: string | null; status: string; evidence: string | null };
type Compliance = { framework: string; controls: Control[]; counts: Record<string, number>; score: number };

const FRAMEWORKS = [
  { id: "soc2", label: "SOC 2" },
  { id: "gdpr", label: "GDPR" },
  { id: "iso27001", label: "ISO 27001" },
];

const REPORT_TYPES = ["activity", "config_changes", "exports", "incidents", "full"];
const REPORT_FORMATS = ["csv", "pdf"];

/** Estado de un control de cumplimiento, en la misma escala que Risk Center. */
const CONTROL_STATUS_META: Record<string, { label: string; tone: Tone; icon: Icon }> = {
  pass: { label: "Pasa", tone: "ok", icon: CheckCircle },
  fail: { label: "Falla", tone: "danger", icon: XCircle },
  review: { label: "En revisión", tone: "warn", icon: Clock },
  na: { label: "No aplica", tone: "neutral", icon: Minus },
};

function ControlStatusBadge({ status }: { status: string }) {
  const meta = CONTROL_STATUS_META[status] ?? {
    label: status || "Sin dato",
    tone: "neutral" as Tone,
    icon: Question,
  };
  return (
    <Badge tone={meta.tone} icon={meta.icon}>
      {meta.label}
    </Badge>
  );
}

const REPORT_COLUMNS: Column<Report>[] = [
  {
    key: "report_type",
    header: "Reporte",
    sortable: true,
    render: (r) => (
      <div className="min-w-0">
        <span className="mono text-xs text-text">{r.report_type}</span>
        <p className="mt-0.5 text-xs text-faint">{r.format.toUpperCase()}</p>
      </div>
    ),
  },
  {
    key: "period_start",
    header: "Periodo",
    hideBelow: "md",
    render: (r) => (
      <span className="text-xs text-muted tabular-nums">
        {r.period_start} — {r.period_end}
      </span>
    ),
  },
  {
    key: "size_bytes",
    header: "Tamaño",
    sortable: true,
    align: "right",
    render: (r) => <span className="mono text-xs text-muted">{(r.size_bytes / 1024).toFixed(1)} KB</span>,
  },
  {
    key: "integrity_hash",
    header: "Hash de integridad",
    hideBelow: "lg",
    render: (r) => <span className="mono text-xs text-faint">{r.integrity_hash.slice(0, 16)}…</span>,
  },
  {
    key: "prev_hash",
    header: "Cadena",
    hideBelow: "xl",
    render: (r) =>
      r.prev_hash ? <Badge tone="info">Encadenado</Badge> : <span className="text-xs text-faint">Sin anterior</span>,
  },
  {
    key: "created_at",
    header: "Creado",
    sortable: true,
    align: "right",
    render: (r) => <span className="text-xs text-muted tabular-nums">{fmtDateTime(r.created_at)}</span>,
  },
];

const CONTROL_COLUMNS: Column<Control>[] = [
  { key: "control_id", header: "Control", sortable: true, render: (c) => <span className="mono text-xs text-text">{c.control_id}</span> },
  { key: "title", header: "Título", sortable: true, render: (c) => <span className="text-[13px] text-muted">{c.title}</span> },
  {
    key: "category",
    header: "Categoría",
    sortable: true,
    hideBelow: "md",
    render: (c) => <span className="text-xs text-faint">{c.category}</span>,
  },
  {
    key: "required_evidence",
    header: "Evidencia requerida",
    hideBelow: "lg",
    render: (c) => <span className="text-xs text-faint">{c.required_evidence ?? "—"}</span>,
  },
  { key: "status", header: "Estado", sortable: true, render: (c) => <ControlStatusBadge status={c.status} /> },
];

const CONTROL_PAGE_SIZE = 15;

function applySort<T>(rows: T[], sort: SortState): T[] {
  if (!sort) return rows;
  const dir = sort.dir === "asc" ? 1 : -1;
  return [...rows].sort((a, b) => {
    const left = (a as unknown as Record<string, unknown>)[sort.key];
    const right = (b as unknown as Record<string, unknown>)[sort.key];
    if (typeof left === "number" && typeof right === "number") return (left - right) * dir;
    return String(left ?? "").localeCompare(String(right ?? ""), "es") * dir;
  });
}

export default function AuditCompliancePage() {
  const { session } = useAuth();
  const [reports, setReports] = useState<Report[]>([]);
  const [compliance, setCompliance] = useState<Compliance | null>(null);
  const [framework, setFramework] = useState("soc2");
  const [form, setForm] = useState({ report_type: "activity", format: "csv" });
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState("");
  const [error, setError] = useState("");
  const [notice, setNotice] = useState<{ tone: "ok" | "warn"; text: string } | null>(null);
  const [reportSort, setReportSort] = useState<SortState>({ key: "created_at", dir: "desc" });
  const [controlSort, setControlSort] = useState<SortState>(null);
  const [controlPage, setControlPage] = useState(1);
  const [control, setControl] = useState<Control | null>(null);
  const [confirmFail, setConfirmFail] = useState<string | null>(null);

  async function load() {
    if (!session) return;
    setError("");
    try {
      const [r, c] = await Promise.all([
        api<{ reports: Report[] }>("/api/v1/audit/reports", { token: session.token, organizationId: session.organizationId }),
        api<Compliance>(`/api/v1/audit/compliance?framework=${framework}`, { token: session.token, organizationId: session.organizationId }),
      ]);
      setReports(r.reports || []);
      setCompliance(c);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Error");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    void load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [session, framework]);

  async function generate() {
    if (!session) return;
    setBusy("gen");
    setError("");
    setNotice(null);
    try {
      const end = new Date().toISOString().slice(0, 10);
      const start = new Date(Date.now() - 30 * 86400000).toISOString().slice(0, 10);
      await api("/api/v1/audit/reports/generate", {
        method: "POST",
        token: session.token,
        organizationId: session.organizationId,
        body: JSON.stringify({ ...form, period_start: start, period_end: end }),
      });
      setNotice({ tone: "ok", text: `Reporte ${form.report_type} generado para el periodo ${start} — ${end}.` });
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Error");
    } finally {
      setBusy("");
    }
  }

  async function verify(id: string) {
    if (!session) return;
    setError("");
    setNotice(null);
    try {
      const v = await api<{ verified: boolean; chain_ok: boolean; current_hash: string }>(
        `/api/v1/audit/reports/${id}/verify`,
        { token: session.token, organizationId: session.organizationId }
      );
      setNotice(
        v.verified && v.chain_ok
          ? { tone: "ok", text: `Integridad verificada: hash propio y cadena coinciden (${v.current_hash.slice(0, 12)}…).` }
          : { tone: "warn", text: "El reporte no coincide con su hash o con la cadena. Revisá la evidencia antes de usarlo." },
      );
    } catch (e) {
      setError(e instanceof Error ? e.message : "Error");
    }
  }

  async function updateControl(controlId: string, status: string) {
    if (!session) return;
    setBusy(`c-${controlId}`);
    setError("");
    try {
      await api("/api/v1/audit/compliance", {
        method: "PUT",
        token: session.token,
        organizationId: session.organizationId,
        body: JSON.stringify({ framework, control_id: controlId, status, evidence: "Revisado en CC" }),
      });
      setNotice({ tone: "ok", text: `Control ${controlId} actualizado a ${CONTROL_STATUS_META[status]?.label ?? status}.` });
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Error");
    } finally {
      setBusy("");
    }
  }

  const sortedReports = useMemo(() => applySort(reports, reportSort), [reports, reportSort]);
  const sortedControls = useMemo(() => applySort(compliance?.controls ?? [], controlSort), [compliance, controlSort]);
  const controlPageRows = sortedControls.slice((controlPage - 1) * CONTROL_PAGE_SIZE, controlPage * CONTROL_PAGE_SIZE);
  const frameworkLabel = FRAMEWORKS.find((f) => f.id === framework)?.label ?? framework;

  return (
    <div className="space-y-4">
      <PageHeader
        title="Audit & Compliance"
        subtitle="Reportes de actividad con hash encadenado y controles de cumplimiento por framework."
      />

      {error && <ErrorInline>{error}</ErrorInline>}
      {notice &&
        (notice.tone === "ok" ? <SuccessInline message={notice.text} /> : <WarningInline message={notice.text} />)}

      {loading ? (
        <div className="panel">
          <div className="panel-body">
            <SkeletonBlock rows={6} />
          </div>
        </div>
      ) : (
        <>
          <MetricGrid>
            <Metric
              label={`Conformidad ${frameworkLabel}`}
              value={`${compliance?.score ?? 0}%`}
              hint={`${compliance?.counts?.pass ?? 0} controles conformes de ${compliance?.controls.length ?? 0}`}
              help="Porcentaje de controles aprobados sobre el total del framework."
            />
            <Metric label="No conformes" value={compliance?.counts?.fail ?? 0} size="md" tone={(compliance?.counts?.fail ?? 0) > 0 ? "danger" : "default"} hint="Controles que fallan" />
            <Metric label="En revisión" value={compliance?.counts?.review ?? 0} size="md" hint="Sin veredicto final" />
            <Metric label="No aplica" value={compliance?.counts?.na ?? 0} size="md" hint="Fuera del alcance" />
          </MetricGrid>

          <Panel>
            <PanelHeader
              title="Generar reporte"
              description="El reporte cubre los últimos 30 días y queda encadenado al hash anterior."
            />
            <div className="panel-body">
              <div className="flex flex-wrap items-end gap-3">
                <Field className="w-full sm:w-52" label="Tipo de reporte">
                  <Select
                    value={form.report_type}
                    onChange={(e) => setForm((f) => ({ ...f, report_type: e.target.value }))}
                  >
                    {REPORT_TYPES.map((t) => (
                      <option key={t} value={t}>
                        {t}
                      </option>
                    ))}
                  </Select>
                </Field>
                <Field className="w-full sm:w-40" label="Formato">
                  <Select value={form.format} onChange={(e) => setForm((f) => ({ ...f, format: e.target.value }))}>
                    {REPORT_FORMATS.map((f) => (
                      <option key={f} value={f}>
                        {f}
                      </option>
                    ))}
                  </Select>
                </Field>
                <FormActions>
                  <Button variant="primary" leadingIcon={FileText} loading={busy === "gen"} disabled={busy !== ""} onClick={() => void generate()}>
                    Generar (30 días)
                  </Button>
                </FormActions>
              </div>
            </div>
          </Panel>

          <div className="space-y-3">
            <SectionHeader
              eyebrow="Reportes"
              title={`Reportes generados (${reports.length})`}
              description="Descargá o verificá la integridad de cada archivo. La verificación compara el hash actual contra el encadenado."
            />
            <DataTable
              columns={REPORT_COLUMNS}
              rows={sortedReports}
              rowKey={(r) => r.id}
              caption="Reportes de auditoría"
              stickyHeader
              sort={reportSort}
              onSortChange={setReportSort}
              rowActions={(r) => (
                <>
                  <Button
                    variant="ghost"
                    size="sm"
                    onClick={() =>
                      session &&
                      window.open(
                        `/api/v1/audit/reports/${r.id}/download?token=${encodeURIComponent(session.token || "")}&organizationId=${encodeURIComponent(session.organizationId)}`,
                        "_blank"
                      )
                    }
                  >
                    Descargar
                  </Button>
                  <Button variant="ghost" size="sm" onClick={() => void verify(r.id)}>
                    Verificar
                  </Button>
                </>
              )}
              empty={
                <EmptyState
                  icon={FileText}
                  title="Sin reportes generados"
                  body="Todavía no se generó ningún reporte para esta organización."
                  hint="Elegí tipo y formato arriba, y se emite en el momento."
                />
              }
              footer={sortedReports.length > 0 ? <ResultCount shown={sortedReports.length} total={reports.length} noun="reportes" /> : undefined}
            />
          </div>

          <div className="space-y-3">
            <SectionHeader
              eyebrow="Cumplimiento"
              title={`Controles · ${frameworkLabel}`}
              description="Cada control declara su evidencia requerida y su veredicto. Seleccioná una fila para inspeccionar y cambiar el estado."
              actions={
                <Select
                  className="w-full sm:w-48"
                  aria-label="Framework de cumplimiento"
                  value={framework}
                  onChange={(e) => {
                    setFramework(e.target.value);
                    setControlPage(1);
                  }}
                >
                  {FRAMEWORKS.map((f) => (
                    <option key={f.id} value={f.id}>
                      {f.label}
                    </option>
                  ))}
                </Select>
              }
            />
            <DataTable
              columns={CONTROL_COLUMNS}
              rows={controlPageRows}
              rowKey={(c) => c.control_id}
              caption={`Controles de ${frameworkLabel}`}
              dense
              stickyHeader
              sort={controlSort}
              onSortChange={(next) => {
                setControlSort(next);
                setControlPage(1);
              }}
              onRowClick={(c) => setControl(c)}
              rowActions={(c) => (
                <Menu
                  label={`Cambiar estado de ${c.control_id}`}
                  trigger={
                    <Button variant="ghost" size="sm" disabled={busy !== ""}>
                      Estado
                    </Button>
                  }
                >
                  <MenuLabel className={menuLabelClass}>Marcar como</MenuLabel>
                  {Object.entries(CONTROL_STATUS_META).map(([id, meta]) => (
                    <MenuItem
                      key={id}
                      className={menuItemClass}
                      disabled={c.status === id}
                      onSelect={() => (id === "fail" ? setConfirmFail(c.control_id) : void updateControl(c.control_id, id))}
                    >
                      <meta.icon size={14} weight="fill" aria-hidden />
                      {meta.label}
                    </MenuItem>
                  ))}
                </Menu>
              )}
              empty={
                <EmptyState
                  icon={ShieldCheck}
                  title="Sin controles cargados"
                  body={`El framework ${frameworkLabel} todavía no tiene controles asociados a esta organización.`}
                />
              }
              footer={
                sortedControls.length > 0 ? (
                  <>
                    <ResultCount shown={controlPageRows.length} total={sortedControls.length} noun="controles" />
                    {sortedControls.length > CONTROL_PAGE_SIZE && (
                      <Pagination page={controlPage} pageSize={CONTROL_PAGE_SIZE} total={sortedControls.length} onPageChange={setControlPage} />
                    )}
                  </>
                ) : undefined
              }
            />
          </div>
        </>
      )}

      <Drawer
        open={Boolean(control)}
        onOpenChange={(open) => !open && setControl(null)}
        title={control ? `Control ${control.control_id}` : "Control"}
        description={control ? `${control.category} · ${frameworkLabel}` : undefined}
        width={520}
        footer={
          control && (
            <Menu
              label="Cambiar estado del control"
              align="end"
              side="top"
              trigger={
                <Button variant="secondary" disabled={busy !== ""}>
                  Cambiar estado
                </Button>
              }
            >
              {Object.entries(CONTROL_STATUS_META).map(([id, meta]) => (
                <MenuItem
                  key={id}
                  className={menuItemClass}
                  disabled={control.status === id}
                  onSelect={() => (id === "fail" ? setConfirmFail(control.control_id) : void updateControl(control.control_id, id))}
                >
                  <meta.icon size={14} weight="fill" aria-hidden />
                  {meta.label}
                </MenuItem>
              ))}
            </Menu>
          )
        }
      >
        {control && (
          <div className="space-y-4">
            <div className="flex flex-wrap items-center gap-2">
              <ControlStatusBadge status={control.status} />
              <Badge tone="neutral">{control.framework}</Badge>
            </div>
            <p className="text-[13px] leading-relaxed text-text">{control.title}</p>
            <KeyValue
              items={[
                { key: "Categoría", value: control.category },
                { key: "Evidencia requerida", value: control.required_evidence ?? "Sin definir" },
                { key: "Evidencia registrada", value: control.evidence ?? "Sin cargar" },
              ]}
            />
            <InfoInline
              className="mb-0"
              message="Cambiar el estado queda auditado con la fecha y el usuario que lo hizo."
            />
          </div>
        )}
      </Drawer>

      <ConfirmDialog
        open={Boolean(confirmFail)}
        onOpenChange={(open) => !open && setConfirmFail(null)}
        title="Marcar control como no conforme"
        body="El control baja el score de conformidad del framework y queda registrado en la auditoría. Podés revertirlo cambiando el estado de nuevo."
        confirmLabel="Marcar como falla"
        onConfirm={() => {
          if (confirmFail) void updateControl(confirmFail, "fail");
          setConfirmFail(null);
        }}
      />
    </div>
  );
}
