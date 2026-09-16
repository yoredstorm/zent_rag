import {
  CheckCircle,
  CircleNotch,
  Clock,
  CloudArrowDown,
  CloudArrowUp,
  Database,
  Question,
  ShieldCheck,
  Timer,
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
  Input,
  KeyValue,
  Metric,
  MetricGrid,
  PageHeader,
  Panel,
  PanelHeader,
  ResultCount,
  SectionHeader,
  Select,
  SkeletonBlock,
  StatusBadge,
  SuccessInline,
  WarningInline,
  type Column,
  type SortState,
  type Tone,
} from "../components/ui";
import { fmtDateTime, fmtLatency } from "../lib/format";

type Policy = { id: string; name: string; scope: string; target_id: string | null; rpo_minutes: number; rto_minutes: number; replication_region: string; status: string; latest_backup_version: number; last_backup_at: string | null };
type Backup = { id: string; scope: string; source_id: string | null; version: number; artifact: Record<string, unknown>; status: string; created_at: string; restored_at: string | null; restored_to_region: string | null };
type Drill = { id: string; policy_id: string; policy_name: string; region: string; status: string; failover_ok: boolean | null; recovery_validated: boolean | null; duration_ms: number | null; detail: string | null; started_at: string };
type Availability = { policies_total: number; policies_active: number; drills_30d: number; drills_success: number; drill_success_rate: number; avg_drill_duration_ms: number; rpo_coverage: number; rpo_covered_policies: number; regions: { regions: { code: string; name: string; status: string }[] } };

/** Estado de políticas, backups y drills del módulo de continuidad. */
const DR_STATUS_META: Record<string, { label: string; tone: Tone; icon: Icon }> = {
  active: { label: "Activa", tone: "ok", icon: CheckCircle },
  paused: { label: "Pausada", tone: "warn", icon: Clock },
  running: { label: "En curso", tone: "accent", icon: CircleNotch },
  success: { label: "Correcto", tone: "ok", icon: CheckCircle },
  failed: { label: "Falló", tone: "danger", icon: XCircle },
  restored: { label: "Restaurado", tone: "info", icon: CloudArrowDown },
};

function DrStatusBadge({ status }: { status: string }) {
  const meta = DR_STATUS_META[status] ?? {
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

/** Bandera booleana del drill: se muestra como estado explícito, no como texto crudo. */
function FlagBadge({ label, value }: { label: string; value: boolean | null }) {
  if (value === null || value === undefined) {
    return <Badge tone="neutral">{label}: sin dato</Badge>;
  }
  return (
    <Badge tone={value ? "ok" : "danger"} icon={value ? CheckCircle : XCircle}>
      {label}: {value ? "OK" : "Falló"}
    </Badge>
  );
}

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

const POLICY_COLUMNS: Column<Policy>[] = [
  {
    key: "name",
    header: "Política",
    sortable: true,
    render: (p) => (
      <div className="min-w-0">
        <p className="truncate text-[13px] font-medium text-text">{p.name}</p>
        <p className="mono mt-0.5 text-xs text-faint">{p.scope}</p>
      </div>
    ),
  },
  {
    key: "rpo_minutes",
    header: "RPO / RTO",
    sortable: true,
    align: "right",
    render: (p) => (
      <span className="text-xs text-muted tabular-nums">
        {p.rpo_minutes} m / {p.rto_minutes} m
      </span>
    ),
  },
  {
    key: "replication_region",
    header: "Réplica",
    sortable: true,
    hideBelow: "md",
    render: (p) => <span className="mono text-xs text-faint">{p.replication_region}</span>,
  },
  {
    key: "latest_backup_version",
    header: "Último backup",
    hideBelow: "lg",
    render: (p) => (
      <span className="text-xs text-muted tabular-nums">
        {p.latest_backup_version > 0 ? `v${p.latest_backup_version} · ${fmtDateTime(p.last_backup_at)}` : "Sin backups"}
      </span>
    ),
  },
  {
    key: "status",
    header: "Estado",
    sortable: true,
    render: (p) => <DrStatusBadge status={p.status} />,
  },
];

const BACKUP_COLUMNS: Column<Backup>[] = [
  {
    key: "version",
    header: "Backup",
    sortable: true,
    render: (b) => (
      <span className="flex items-center gap-2">
        <Badge tone="neutral">v{b.version}</Badge>
        <span className="mono text-xs text-faint">{b.scope}</span>
      </span>
    ),
  },
  {
    key: "status",
    header: "Estado",
    sortable: true,
    render: (b) => <DrStatusBadge status={b.status} />,
  },
  {
    key: "restored_to_region",
    header: "Restaurado en",
    hideBelow: "md",
    render: (b) =>
      b.restored_to_region ? (
        <span className="mono text-xs text-muted">{b.restored_to_region}</span>
      ) : (
        <span className="text-xs text-faint">—</span>
      ),
  },
  {
    key: "created_at",
    header: "Creado",
    sortable: true,
    align: "right",
    render: (b) => <span className="text-xs text-muted tabular-nums">{fmtDateTime(b.created_at)}</span>,
  },
];

const DRILL_COLUMNS: Column<Drill>[] = [
  {
    key: "policy_name",
    header: "Política",
    sortable: true,
    render: (d) => <span className="text-[13px] text-text">{d.policy_name}</span>,
  },
  {
    key: "region",
    header: "Región",
    sortable: true,
    hideBelow: "md",
    render: (d) => <span className="mono text-xs text-faint">{d.region}</span>,
  },
  {
    key: "status",
    header: "Estado",
    sortable: true,
    render: (d) => <DrStatusBadge status={d.status} />,
  },
  {
    key: "failover_ok",
    header: "Failover",
    render: (d) => <FlagBadge label="Failover" value={d.failover_ok} />,
  },
  {
    key: "recovery_validated",
    header: "Recovery",
    hideBelow: "lg",
    render: (d) => <FlagBadge label="Recovery" value={d.recovery_validated} />,
  },
  {
    key: "duration_ms",
    header: "Duración",
    sortable: true,
    align: "right",
    hideBelow: "xl",
    render: (d) => <span className="mono text-xs text-muted">{fmtLatency(d.duration_ms)}</span>,
  },
  {
    key: "started_at",
    header: "Inicio",
    sortable: true,
    align: "right",
    render: (d) => <span className="text-xs text-muted tabular-nums">{fmtDateTime(d.started_at)}</span>,
  },
];

const DEFAULT_REPLICATION_REGION = "eu-west-1";

export default function DisasterRecoveryPage() {
  const { session } = useAuth();
  const [policies, setPolicies] = useState<Policy[]>([]);
  const [backups, setBackups] = useState<Backup[]>([]);
  const [drills, setDrills] = useState<Drill[]>([]);
  const [avail, setAvail] = useState<Availability | null>(null);
  const [draft, setDraft] = useState({ name: "", scope: "agent", rpo_minutes: 60, rto_minutes: 15, replication_region: DEFAULT_REPLICATION_REGION });
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState("");
  const [error, setError] = useState("");
  const [notice, setNotice] = useState<{ tone: "ok" | "warn"; text: string } | null>(null);
  const [policySort, setPolicySort] = useState<SortState>(null);
  const [backupSort, setBackupSort] = useState<SortState>({ key: "created_at", dir: "desc" });
  const [drillSort, setDrillSort] = useState<SortState>({ key: "started_at", dir: "desc" });
  const [policy, setPolicy] = useState<Policy | null>(null);
  const [backupDetail, setBackupDetail] = useState<Backup | null>(null);
  const [drillDetail, setDrillDetail] = useState<Drill | null>(null);
  const [confirmDrill, setConfirmDrill] = useState<string | null>(null);
  const [confirmRestore, setConfirmRestore] = useState<Backup | null>(null);

  async function load() {
    if (!session) return;
    setError("");
    try {
      const [p, b, d, a] = await Promise.all([
        api<{ policies: Policy[] }>("/api/v1/dr/policies", { token: session.token, organizationId: session.organizationId }),
        api<{ backups: Backup[] }>("/api/v1/dr/backups", { token: session.token, organizationId: session.organizationId }),
        api<{ drills: Drill[] }>("/api/v1/dr/drills", { token: session.token, organizationId: session.organizationId }),
        api<Availability>("/api/v1/dr/availability", { token: session.token, organizationId: session.organizationId }),
      ]);
      setPolicies(p.policies || []);
      setBackups(b.backups || []);
      setDrills(d.drills || []);
      setAvail(a);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Error");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    void load();
    const id = setInterval(() => void load(), 15000);
    return () => clearInterval(id);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [session]);

  async function createPolicy() {
    if (!session || !draft.name) return;
    setBusy("create");
    setError("");
    setNotice(null);
    try {
      const out = await api<{ policy_id: string }>("/api/v1/dr/policies", {
        method: "POST",
        token: session.token,
        organizationId: session.organizationId,
        body: JSON.stringify(draft),
      });
      setNotice({ tone: "ok", text: `Política creada (${out.policy_id.slice(0, 8)}…).` });
      setDraft({ name: "", scope: "agent", rpo_minutes: 60, rto_minutes: 15, replication_region: DEFAULT_REPLICATION_REGION });
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Error");
    } finally {
      setBusy("");
    }
  }

  async function backup(policy: Policy) {
    if (!session) return;
    setBusy(`bk-${policy.id.slice(0, 6)}`);
    setError("");
    setNotice(null);
    try {
      const out = await api<{ backup_id: string; version: number }>("/api/v1/dr/backups", {
        method: "POST",
        token: session.token,
        organizationId: session.organizationId,
        body: JSON.stringify({ scope: policy.scope, source_id: policy.target_id }),
      });
      setNotice({ tone: "ok", text: `Backup v${out.version} creado para ${policy.name}.` });
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Error");
    } finally {
      setBusy("");
    }
  }

  async function restore(backupId: string) {
    if (!session) return;
    setBusy(`rs-${backupId.slice(0, 6)}`);
    setError("");
    setNotice(null);
    try {
      const out = await api<Record<string, unknown>>(`/api/v1/dr/backups/${backupId}/restore`, {
        method: "POST",
        token: session.token,
        organizationId: session.organizationId,
        body: JSON.stringify({ region: "us-east-1" }),
      });
      setNotice({ tone: "ok", text: `Restauración ejecutada: ${JSON.stringify(out).slice(0, 120)}` });
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Error");
    } finally {
      setBusy("");
    }
  }

  async function drill(policyId: string) {
    if (!session) return;
    setBusy(`dl-${policyId.slice(0, 6)}`);
    setError("");
    setNotice(null);
    try {
      const out = await api<{ status: string; failover_ok: boolean; recovery_validated: boolean; detail: string }>("/api/v1/dr/drills", {
        method: "POST",
        token: session.token,
        organizationId: session.organizationId,
        body: JSON.stringify({ policy_id: policyId }),
      });
      setNotice({
        tone: out.status === "success" ? "ok" : "warn",
        text: `Drill ${out.status}: failover ${out.failover_ok ? "OK" : "falló"} · recovery ${out.recovery_validated ? "validado" : "no validado"} — ${out.detail}`,
      });
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Error");
    } finally {
      setBusy("");
    }
  }

  async function act(policyId: string, action: "pause" | "resume") {
    if (!session) return;
    setBusy(`${action}-${policyId.slice(0, 6)}`);
    setError("");
    setNotice(null);
    try {
      await api(`/api/v1/dr/policies/${policyId}/${action}`, { method: "POST", token: session.token, organizationId: session.organizationId });
      setNotice({ tone: "ok", text: action === "pause" ? "Política pausada." : "Política reanudada." });
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Error");
    } finally {
      setBusy("");
    }
  }

  const sortedPolicies = useMemo(() => applySort(policies, policySort), [policies, policySort]);
  const sortedBackups = useMemo(() => applySort(backups, backupSort), [backups, backupSort]);
  const sortedDrills = useMemo(() => applySort(drills, drillSort), [drills, drillSort]);

  /** Regiones reales reportadas por la plataforma; el valor actual siempre queda disponible. */
  const regionOptions = useMemo(() => {
    const codes = Array.from(new Set((avail?.regions?.regions ?? []).map((r) => r.code)));
    return codes.includes(draft.replication_region) ? codes : [draft.replication_region, ...codes];
  }, [avail, draft.replication_region]);

  const policyActions = (p: Policy) => (
    <>
      <Button
        variant="ghost"
        size="sm"
        leadingIcon={CloudArrowUp}
        disabled={busy !== ""}
        loading={busy === `bk-${p.id.slice(0, 6)}`}
        onClick={() => void backup(p)}
      >
        Backup
      </Button>
      <Button
        variant="ghost"
        size="sm"
        leadingIcon={Timer}
        disabled={busy !== ""}
        onClick={() => setConfirmDrill(p.id)}
      >
        Drill
      </Button>
      {p.status === "active" ? (
        <Button variant="ghost" size="sm" disabled={busy !== ""} onClick={() => void act(p.id, "pause")}>
          Pausar
        </Button>
      ) : (
        <Button variant="ghost" size="sm" disabled={busy !== ""} onClick={() => void act(p.id, "resume")}>
          Reanudar
        </Button>
      )}
    </>
  );

  return (
    <div className="space-y-4">
      <PageHeader
        title="Disaster Recovery"
        subtitle="Políticas RPO/RTO, backups versionados con restore y drills de failover multi-región."
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
              label="Cobertura RPO"
              value={`${avail?.rpo_coverage ?? 0}%`}
              hint={`${avail?.rpo_covered_policies ?? 0} políticas dentro del RPO declarado`}
              help="Políticas cuyo último backup cumple el RPO configurado."
            />
            <Metric
              label="Drills (30 días)"
              value={avail?.drills_30d ?? 0}
              size="md"
              hint={`${avail?.drill_success_rate ?? 0}% de éxito · ${avail?.drills_success ?? 0} correctos`}
            />
            <Metric label="Duración media del drill" value={fmtLatency(avail?.avg_drill_duration_ms)} size="md" />
            <Metric
              label="Políticas activas"
              value={`${avail?.policies_active ?? 0}/${avail?.policies_total ?? 0}`}
              size="md"
              hint={`${policies.length} políticas en esta organización`}
            />
          </MetricGrid>

          <div className="grid grid-cols-1 gap-4 lg:grid-cols-3 lg:items-start">
            <div className="lg:col-span-2">
              <DataTable
                columns={POLICY_COLUMNS}
                rows={sortedPolicies}
                rowKey={(p) => p.id}
                caption="Políticas de continuidad"
                stickyHeader
                sort={policySort}
                onSortChange={setPolicySort}
                onRowClick={(p) => setPolicy(p)}
                rowActions={policyActions}
                empty={
                  <EmptyState
                    icon={ShieldCheck}
                    title="Sin políticas de continuidad"
                    body="No hay políticas RPO/RTO definidas para esta organización."
                    hint="Creá una a la derecha para habilitar backups y drills."
                  />
                }
                footer={sortedPolicies.length > 0 ? <ResultCount shown={sortedPolicies.length} total={policies.length} noun="políticas" /> : undefined}
              />
            </div>

            <div className="space-y-4">
              <Panel>
                <PanelHeader title="Nueva política" description="Define alcance, RPO/RTO y región de réplica." />
                <div className="panel-body flex flex-col gap-4">
                  <Field label="Nombre">
                    <Input
                      value={draft.name}
                      onChange={(e) => setDraft((d) => ({ ...d, name: e.target.value }))}
                      placeholder="Ej. Copilot producción"
                    />
                  </Field>
                  <Field label="Alcance">
                    <Select value={draft.scope} onChange={(e) => setDraft((d) => ({ ...d, scope: e.target.value }))}>
                      {["agent", "knowledge", "full"].map((s) => (
                        <option key={s} value={s}>
                          {s}
                        </option>
                      ))}
                    </Select>
                  </Field>
                  <div className="grid grid-cols-2 gap-3">
                    <Field label="RPO (min)" hint="Pérdida máxima aceptada.">
                      <Input
                        type="number"
                        min={1}
                        value={draft.rpo_minutes}
                        onChange={(e) => setDraft((d) => ({ ...d, rpo_minutes: Number(e.target.value) }))}
                      />
                    </Field>
                    <Field label="RTO (min)" hint="Tiempo máximo de recuperación.">
                      <Input
                        type="number"
                        min={1}
                        value={draft.rto_minutes}
                        onChange={(e) => setDraft((d) => ({ ...d, rto_minutes: Number(e.target.value) }))}
                      />
                    </Field>
                  </div>
                  <Field label="Región de réplica">
                    <Select
                      value={draft.replication_region}
                      onChange={(e) => setDraft((d) => ({ ...d, replication_region: e.target.value }))}
                    >
                      {regionOptions.map((r) => (
                        <option key={r} value={r}>
                          {r}
                        </option>
                      ))}
                    </Select>
                  </Field>
                  <FormActions>
                    <Button variant="primary" loading={busy === "create"} disabled={busy !== "" || !draft.name} onClick={() => void createPolicy()}>
                      Crear política
                    </Button>
                  </FormActions>
                </div>
              </Panel>

              <Panel>
                <PanelHeader title="Regiones" description="Estado de las regiones reportado por la plataforma." />
                <div className="panel-body">
                  {(avail?.regions?.regions ?? []).length === 0 ? (
                    <p className="text-[13px] leading-relaxed text-muted">La plataforma no reportó regiones.</p>
                  ) : (
                    <ul className="flex flex-wrap gap-1.5">
                      {(avail?.regions?.regions ?? []).map((r) => (
                        <li key={r.code}>
                          <StatusBadge status={r.status} label={`${r.code} · ${r.name}`} />
                        </li>
                      ))}
                    </ul>
                  )}
                </div>
              </Panel>
            </div>
          </div>

          <div className="grid grid-cols-1 gap-4 lg:grid-cols-2 lg:items-start">
            <div className="space-y-3">
              <SectionHeader
                eyebrow="Backups"
                title={`Backups (${backups.length})`}
                description="Cada restauración reemplaza el estado actual y queda auditada."
              />
              <DataTable
                columns={BACKUP_COLUMNS}
                rows={sortedBackups}
                rowKey={(b) => b.id}
                caption="Backups versionados"
                dense
                sort={backupSort}
                onSortChange={setBackupSort}
                onRowClick={(b) => setBackupDetail(b)}
                rowActions={(b) => (
                  <Button
                    variant="ghost"
                    size="sm"
                    leadingIcon={CloudArrowDown}
                    disabled={busy !== "" || b.status === "restored"}
                    onClick={() => setConfirmRestore(b)}
                  >
                    Restaurar
                  </Button>
                )}
                empty={
                  <EmptyState
                    icon={Database}
                    title="Sin backups todavía"
                    body="Los backups se crean desde una política de continuidad."
                    hint="Usá «Backup» en la tabla de políticas."
                  />
                }
                footer={sortedBackups.length > 0 ? <ResultCount shown={sortedBackups.length} total={backups.length} noun="backups" /> : undefined}
              />
            </div>

            <div className="space-y-3">
              <SectionHeader
                eyebrow="Drills"
                title={`Drills recientes (${drills.length})`}
                description="Cada corrida valida failover y recuperación contra la región indicada."
              />
              <DataTable
                columns={DRILL_COLUMNS}
                rows={sortedDrills}
                rowKey={(d) => d.id}
                caption="Drills de failover"
                dense
                sort={drillSort}
                onSortChange={setDrillSort}
                onRowClick={(d) => setDrillDetail(d)}
                empty={
                  <EmptyState
                    icon={Timer}
                    title="Sin drills ejecutados"
                    body="Todavía no se probó el failover de ninguna política."
                    hint="Ejecutá un drill desde una política para validar el plan."
                  />
                }
                footer={sortedDrills.length > 0 ? <ResultCount shown={sortedDrills.length} total={drills.length} noun="drills" /> : undefined}
              />
            </div>
          </div>
        </>
      )}

      <Drawer
        open={Boolean(policy)}
        onOpenChange={(open) => !open && setPolicy(null)}
        title={policy?.name ?? "Política"}
        description={policy ? `${policy.scope} · réplica en ${policy.replication_region}` : undefined}
        width={520}
        footer={policy && policyActions(policy)}
      >
        {policy && (
          <div className="space-y-4">
            <div className="flex flex-wrap items-center gap-2">
              <DrStatusBadge status={policy.status} />
              <Badge tone="neutral">Backups v{policy.latest_backup_version}</Badge>
            </div>
            <KeyValue
              columns={2}
              items={[
                { key: "RPO", value: `${policy.rpo_minutes} min` },
                { key: "RTO", value: `${policy.rto_minutes} min` },
                { key: "Último backup", value: policy.last_backup_at ? fmtDateTime(policy.last_backup_at) : "Sin backups" },
                { key: "Objetivo", value: policy.target_id ?? "Todos", mono: Boolean(policy.target_id) },
              ]}
            />
            <InfoInline
              className="mb-0"
              message="Un drill simula el failover y registra el resultado; no reemplaza datos."
            />
          </div>
        )}
      </Drawer>

      <Drawer
        open={Boolean(backupDetail)}
        onOpenChange={(open) => !open && setBackupDetail(null)}
        title={backupDetail ? `Backup v${backupDetail.version}` : "Backup"}
        description={backupDetail?.scope}
        width={520}
        footer={
          backupDetail && (
            <Button
              variant="secondary"
              leadingIcon={CloudArrowDown}
              disabled={busy !== "" || backupDetail.status === "restored"}
              onClick={() => setConfirmRestore(backupDetail)}
            >
              Restaurar en us-east-1
            </Button>
          )
        }
      >
        {backupDetail && (
          <div className="space-y-4">
            <div className="flex flex-wrap items-center gap-2">
              <DrStatusBadge status={backupDetail.status} />
              {backupDetail.restored_to_region && <Badge tone="info">Restaurado en {backupDetail.restored_to_region}</Badge>}
            </div>
            <KeyValue
              columns={2}
              items={[
                { key: "Creado", value: fmtDateTime(backupDetail.created_at) },
                { key: "Restaurado", value: backupDetail.restored_at ? fmtDateTime(backupDetail.restored_at) : "Nunca" },
                { key: "Origen", value: backupDetail.source_id ?? "—", mono: Boolean(backupDetail.source_id) },
              ]}
            />
            <div>
              <p className="eyebrow mb-2">Artefacto</p>
              <div className="rounded-md border border-border bg-control p-3 font-mono text-xs leading-relaxed break-all text-muted">
                {JSON.stringify(backupDetail.artifact)}
              </div>
            </div>
          </div>
        )}
      </Drawer>

      <Drawer
        open={Boolean(drillDetail)}
        onOpenChange={(open) => !open && setDrillDetail(null)}
        title="Drill de failover"
        description={drillDetail ? `${drillDetail.policy_name} · ${drillDetail.region}` : undefined}
        width={520}
      >
        {drillDetail && (
          <div className="space-y-4">
            <div className="flex flex-wrap items-center gap-2">
              <DrStatusBadge status={drillDetail.status} />
              <FlagBadge label="Failover" value={drillDetail.failover_ok} />
              <FlagBadge label="Recovery" value={drillDetail.recovery_validated} />
            </div>
            <KeyValue
              columns={2}
              items={[
                { key: "Inicio", value: fmtDateTime(drillDetail.started_at) },
                { key: "Duración", value: fmtLatency(drillDetail.duration_ms) },
              ]}
            />
            {drillDetail.detail && (
              <div>
                <p className="eyebrow mb-2">Detalle</p>
                <p className="text-[13px] leading-relaxed text-muted">{drillDetail.detail}</p>
              </div>
            )}
          </div>
        )}
      </Drawer>

      <ConfirmDialog
        open={Boolean(confirmDrill)}
        onOpenChange={(open) => !open && setConfirmDrill(null)}
        title="Ejecutar drill de failover"
        body="Se lanza una corrida contra la región de réplica de la política y queda registrada en el historial con su resultado."
        confirmLabel="Ejecutar drill"
        tone="primary"
        onConfirm={() => {
          if (confirmDrill) void drill(confirmDrill);
          setConfirmDrill(null);
        }}
      />

      <ConfirmDialog
        open={Boolean(confirmRestore)}
        onOpenChange={(open) => !open && setConfirmRestore(null)}
        title={confirmRestore ? `Restaurar backup v${confirmRestore.version}` : "Restaurar backup"}
        body={`La restauración reemplaza el estado actual de ${confirmRestore?.scope ?? "los datos"} con este backup en us-east-1. No se puede deshacer.`}
        confirmLabel="Restaurar"
        onConfirm={() => {
          if (confirmRestore) void restore(confirmRestore.id);
          setConfirmRestore(null);
        }}
      />
    </div>
  );
}
