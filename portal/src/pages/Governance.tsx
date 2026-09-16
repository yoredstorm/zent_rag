import {
  Anchor,
  CheckCircle,
  Clock,
  Fingerprint,
  Prohibit,
  Question,
  Scales,
  ShieldCheck,
  UserCheck,
  XCircle,
  type Icon,
} from "@phosphor-icons/react";
import { useEffect, useMemo, useState } from "react";
import { api } from "../api";
import { useAuth } from "../auth";
import {
  Badge,
  Button,
  CodeBlock,
  ConfirmDialog,
  CopyButton,
  DataTable,
  Drawer,
  EmptyState,
  ErrorInline,
  Field,
  FormActions,
  Input,
  KeyValue,
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
  StatusBadge,
  SuccessInline,
  WarningInline,
  type Column,
  type SortState,
  type Tone,
} from "../components/ui";
import { fmtDateTime } from "../lib/format";

type Policy = { id: string; policy_type: string; name: string; content: string; version: number; status: string; updated_at: string };
type Decision = { id: string; decision_type: string; target_id: string | null; title: string; rationale: string | null; status: string; approvers: { user_id: string; name: string; approved: boolean; approved_at: string; signature: string }[]; required_approvals: number; decided_at: string | null; created_at: string };
type AuditEntry = { id: string; actor_name: string; action: string; entity_type: string; detail: string; prev_hash: string; hash: string; created_at: string };
type Cert = { id: string; member_name: string; certification: string; issued_at: string; expires_at: string; status: string };
type Report = { total_score: number; pillars: Record<string, { score: number; detail: string }> };

/** Estado de una decisión de la junta. */
const DECISION_STATUS_META: Record<string, { label: string; tone: Tone; icon: Icon }> = {
  pending: { label: "Pendiente", tone: "warn", icon: Clock },
  approved: { label: "Aprobada", tone: "ok", icon: CheckCircle },
  rejected: { label: "Rechazada", tone: "danger", icon: XCircle },
};

function DecisionStatusBadge({ status }: { status: string }) {
  const meta = DECISION_STATUS_META[status] ?? {
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

/** Vigencia derivada de las certificaciones (no hay endpoint de recálculo). */
function certExpiry(expiresAt: string): { label: string; tone: Tone; icon: Icon } | null {
  const t = Date.parse(expiresAt);
  if (Number.isNaN(t)) return null;
  const days = Math.ceil((t - Date.now()) / 86400000);
  if (days < 0) return { label: "Vencida", tone: "danger", icon: XCircle };
  if (days <= 30) return { label: `Vence en ${days} d`, tone: "warn", icon: Clock };
  return null;
}

const DECISION_COLUMNS: Column<Decision>[] = [
  {
    key: "title",
    header: "Decisión",
    sortable: true,
    render: (d) => (
      <div className="min-w-0">
        <p className="truncate text-[13px] font-medium text-text">{d.title}</p>
        {d.rationale && <p className="mt-0.5 line-clamp-1 text-xs text-faint">{d.rationale}</p>}
      </div>
    ),
  },
  {
    key: "decision_type",
    header: "Tipo",
    sortable: true,
    hideBelow: "md",
    render: (d) => <span className="mono text-xs text-muted">{d.decision_type}</span>,
  },
  {
    key: "status",
    header: "Estado",
    sortable: true,
    render: (d) => <DecisionStatusBadge status={d.status} />,
  },
  {
    key: "required_approvals",
    header: "Firmas",
    align: "right",
    render: (d) => (
      <span className="text-xs text-muted tabular-nums">
        {d.approvers.length}/{d.required_approvals}
      </span>
    ),
  },
  {
    key: "created_at",
    header: "Creada",
    sortable: true,
    hideBelow: "lg",
    render: (d) => <span className="text-xs text-muted tabular-nums">{fmtDateTime(d.created_at)}</span>,
  },
];

const AUDIT_COLUMNS: Column<AuditEntry>[] = [
  {
    key: "actor_name",
    header: "Actor",
    sortable: true,
    render: (a) => <span className="text-[13px] text-text">{a.actor_name}</span>,
  },
  {
    key: "action",
    header: "Acción",
    sortable: true,
    render: (a) => <span className="mono text-xs text-muted">{a.action}</span>,
  },
  {
    key: "entity_type",
    header: "Entidad",
    sortable: true,
    hideBelow: "md",
    render: (a) => <span className="text-xs text-faint">{a.entity_type}</span>,
  },
  {
    key: "detail",
    header: "Detalle",
    hideBelow: "lg",
    render: (a) => <span className="line-clamp-1 text-xs text-muted">{a.detail}</span>,
  },
  {
    key: "hash",
    header: "Hash",
    hideBelow: "xl",
    render: (a) => <span className="mono text-xs text-faint">{a.hash.slice(0, 12)}…</span>,
  },
  {
    key: "created_at",
    header: "Fecha",
    sortable: true,
    align: "right",
    render: (a) => <span className="text-xs text-muted tabular-nums">{fmtDateTime(a.created_at)}</span>,
  },
];

const POLICY_COLUMNS: Column<Policy>[] = [
  {
    key: "name",
    header: "Política",
    sortable: true,
    render: (p) => (
      <div className="min-w-0">
        <p className="truncate text-[13px] font-medium text-text">{p.name}</p>
        <p className="mono mt-0.5 text-xs text-faint">{p.policy_type}</p>
      </div>
    ),
  },
  {
    key: "version",
    header: "Versión",
    align: "right",
    render: (p) => <Badge tone="neutral">v{p.version}</Badge>,
  },
  {
    key: "status",
    header: "Estado",
    sortable: true,
    render: (p) => <StatusBadge status={p.status} />,
  },
  {
    key: "updated_at",
    header: "Actualizada",
    sortable: true,
    align: "right",
    render: (p) => <span className="text-xs text-muted tabular-nums">{fmtDateTime(p.updated_at)}</span>,
  },
];

const CERT_COLUMNS: Column<Cert>[] = [
  {
    key: "member_name",
    header: "Miembro",
    sortable: true,
    render: (c) => <span className="text-[13px] text-text">{c.member_name}</span>,
  },
  {
    key: "certification",
    header: "Certificación",
    sortable: true,
    render: (c) => <span className="text-xs text-muted">{c.certification}</span>,
  },
  {
    key: "expires_at",
    header: "Vence",
    sortable: true,
    render: (c) => {
      const expiry = certExpiry(c.expires_at);
      return (
        <span className="flex flex-wrap items-center gap-1.5">
          <span className="text-xs text-muted tabular-nums">{fmtDateTime(c.expires_at)}</span>
          {expiry && (
            <Badge tone={expiry.tone} icon={expiry.icon}>
              {expiry.label}
            </Badge>
          )}
        </span>
      );
    },
  },
  {
    key: "status",
    header: "Estado",
    render: (c) => <StatusBadge status={c.status} />,
  },
];

const PAGE_SIZE = 10;

export default function GovernancePage() {
  const { session } = useAuth();
  const [policies, setPolicies] = useState<Policy[]>([]);
  const [decisions, setDecisions] = useState<Decision[]>([]);
  const [audit, setAudit] = useState<AuditEntry[]>([]);
  const [auditOk, setAuditOk] = useState<boolean | null>(null);
  const [certs, setCerts] = useState<Cert[]>([]);
  const [report, setReport] = useState<Report | null>(null);
  const [draftDecision, setDraftDecision] = useState({ decision_type: "deploy_approval", title: "", rationale: "" });
  const [certDraft, setCertDraft] = useState({ member_name: "", certification: "AI Ethics" });
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState("");
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [decisionSort, setDecisionSort] = useState<SortState>({ key: "created_at", dir: "desc" });
  const [auditSort, setAuditSort] = useState<SortState>({ key: "created_at", dir: "desc" });
  const [certSort, setCertSort] = useState<SortState>(null);
  const [policySort, setPolicySort] = useState<SortState>(null);
  const [auditPage, setAuditPage] = useState(1);
  const [policy, setPolicy] = useState<Policy | null>(null);
  const [decision, setDecision] = useState<Decision | null>(null);
  const [auditEntry, setAuditEntry] = useState<AuditEntry | null>(null);
  const [confirmDecision, setConfirmDecision] = useState<{ id: string; approve: boolean } | null>(null);

  async function load(): Promise<Decision[] | null> {
    if (!session) return null;
    setError("");
    try {
      const [p, d, a, c, r] = await Promise.all([
        api<{ policies: Policy[] }>("/api/v1/governance/policies", { token: session.token, organizationId: session.organizationId }),
        api<{ decisions: Decision[] }>("/api/v1/governance/decisions", { token: session.token, organizationId: session.organizationId }),
        api<{ entries: AuditEntry[] }>("/api/v1/governance/audit", { token: session.token, organizationId: session.organizationId }),
        api<{ certifications: Cert[] }>("/api/v1/governance/certifications", { token: session.token, organizationId: session.organizationId }),
        api<Report>("/api/v1/governance/report", { token: session.token, organizationId: session.organizationId }),
      ]);
      const decisions = d.decisions || [];
      setPolicies(p.policies || []);
      setDecisions(decisions);
      setAudit(a.entries || []);
      setCerts(c.certifications || []);
      setReport(r);
      return decisions;
    } catch (err) {
      setError(err instanceof Error ? err.message : "Error");
      return null;
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    void load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [session]);

  async function decide(decisionId: string, approve: boolean) {
    if (!session) return;
    setBusy(`${approve ? "ok" : "no"}-${decisionId.slice(0, 6)}`);
    setError("");
    setNotice("");
    try {
      const out = await api<{ status: string; approvals: number }>(`/api/v1/governance/decisions/${decisionId}/decide`, {
        method: "POST",
        token: session.token,
        organizationId: session.organizationId,
        body: JSON.stringify({ approve }),
      });
      setNotice(`${approve ? "Aprobada" : "Rechazada"}: ${out.status} (${out.approvals} firmas).`);
      const updated = await load();
      if (updated && decision?.id === decisionId) {
        setDecision(updated.find((d) => d.id === decisionId) ?? null);
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : "Error");
    } finally {
      setBusy("");
    }
  }

  async function createDecision() {
    if (!session || !draftDecision.title) return;
    setBusy("create");
    setError("");
    setNotice("");
    try {
      await api("/api/v1/governance/decisions", {
        method: "POST",
        token: session.token,
        organizationId: session.organizationId,
        body: JSON.stringify(draftDecision),
      });
      setDraftDecision({ decision_type: "deploy_approval", title: "", rationale: "" });
      setNotice("Decisión creada. Espera las firmas requeridas.");
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Error");
    } finally {
      setBusy("");
    }
  }

  async function addCert() {
    if (!session || !certDraft.member_name) return;
    setBusy("cert");
    setError("");
    setNotice("");
    try {
      await api("/api/v1/governance/certifications", {
        method: "POST",
        token: session.token,
        organizationId: session.organizationId,
        body: JSON.stringify(certDraft),
      });
      setCertDraft({ member_name: "", certification: "AI Ethics" });
      setNotice("Certificación registrada.");
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Error");
    } finally {
      setBusy("");
    }
  }

  async function verifyAudit() {
    if (!session) return;
    setBusy("verify");
    setError("");
    setNotice("");
    try {
      const out = await api<{ intact: boolean; verified: number; tampered: string[] }>("/api/v1/governance/audit/verify", {
        method: "POST",
        token: session.token,
        organizationId: session.organizationId,
      });
      setAuditOk(out.intact);
      if (out.intact) {
        setNotice(`Auditoría íntegra: ${out.verified} entradas verificadas contra su hash anterior.`);
      } else {
        setError(`Cadena rota: ${out.tampered.length} entradas no coinciden con su hash. Revisá los hashes antes de exportar.`);
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : "Error");
    } finally {
      setBusy("");
    }
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

  const sortedPolicies = useMemo(() => applySort(policies, policySort), [policies, policySort]);
  const sortedDecisions = useMemo(() => applySort(decisions, decisionSort), [decisions, decisionSort]);
  const sortedCerts = useMemo(() => applySort(certs, certSort), [certs, certSort]);
  const sortedAudit = useMemo(() => applySort(audit, auditSort), [audit, auditSort]);
  const auditPageRows = sortedAudit.slice((auditPage - 1) * PAGE_SIZE, auditPage * PAGE_SIZE);

  return (
    <div className="space-y-4">
      <PageHeader
        title="Governance Board"
        subtitle="Políticas versionadas, decisiones con firmas, auditoría encadenada por hash y reporte ejecutivo."
      />

      {error && <ErrorInline>{error}</ErrorInline>}
      {notice && <SuccessInline message={notice} />}

      {loading ? (
        <div className="panel">
          <div className="panel-body">
            <SkeletonBlock rows={6} />
          </div>
        </div>
      ) : (
        <>
          <Panel>
            <PanelHeader
              title={`Reporte ejecutivo · ${report?.total_score ?? 0}`}
              description="Puntaje por pilar de gobierno, calculado sobre políticas, decisiones, certificaciones y auditoría."
              actions={
                <Button variant="secondary" loading={busy === "verify"} disabled={busy !== ""} onClick={() => void verifyAudit()}>
                  Verificar integridad
                </Button>
              }
            />
            <div className="panel-body">
              {Object.keys(report?.pillars ?? {}).length === 0 ? (
                <p className="text-[13px] leading-relaxed text-muted">
                  El reporte se completa cuando hay políticas, decisiones y certificaciones cargadas.
                </p>
              ) : (
                <MetricGrid cols={4}>
                  {Object.entries(report?.pillars ?? {}).map(([key, p]) => (
                    <Metric key={key} label={key} value={p.score} hint={p.detail} size="md" />
                  ))}
                </MetricGrid>
              )}
              {auditOk === false && (
                <WarningInline
                  className="mt-4 mb-0"
                  message="La verificación detectó entradas alteradas: la cadena de auditoría no es íntegra."
                />
              )}
            </div>
          </Panel>

          <div className="grid grid-cols-1 gap-4 lg:grid-cols-3 lg:items-start">
            <div className="lg:col-span-2">
              <DataTable
                columns={DECISION_COLUMNS}
                rows={sortedDecisions}
                rowKey={(d) => d.id}
                caption="Decisiones de la junta"
                stickyHeader
                sort={decisionSort}
                onSortChange={setDecisionSort}
                onRowClick={(d) => setDecision(d)}
                empty={
                  <EmptyState
                    icon={Anchor}
                    title="Sin decisiones registradas"
                    body="Todavía no se abrieron decisiones de gobierno en esta organización."
                    hint="Creá una decisión y va a pedir las firmas indicadas."
                  />
                }
                footer={sortedDecisions.length > 0 ? <ResultCount shown={sortedDecisions.length} total={decisions.length} noun="decisiones" /> : undefined}
              />
            </div>

            <Panel>
              <PanelHeader title="Nueva decisión" description="Queda pendiente hasta juntar las firmas requeridas." />
              <div className="panel-body flex flex-col gap-4">
                <Field label="Tipo de decisión">
                  <Select
                    value={draftDecision.decision_type}
                    onChange={(e) => setDraftDecision((d) => ({ ...d, decision_type: e.target.value }))}
                  >
                    {["deploy_approval", "incident_review", "policy_change", "model_change"].map((t) => (
                      <option key={t} value={t}>
                        {t}
                      </option>
                    ))}
                  </Select>
                </Field>
                <Field label="Título">
                  <Input
                    value={draftDecision.title}
                    onChange={(e) => setDraftDecision((d) => ({ ...d, title: e.target.value }))}
                    placeholder="Qué se decide y sobre qué"
                  />
                </Field>
                <FormActions>
                  <Button variant="primary" loading={busy === "create"} disabled={busy !== "" || !draftDecision.title} onClick={() => void createDecision()}>
                    Crear decisión
                  </Button>
                </FormActions>
              </div>
            </Panel>
          </div>

          <div className="grid grid-cols-1 gap-4 lg:grid-cols-3 lg:items-start">
            <div className="lg:col-span-2">
              <DataTable
                columns={AUDIT_COLUMNS}
                rows={auditPageRows}
                rowKey={(a) => a.id}
                caption="Auditoría encadenada"
                dense
                stickyHeader
                sort={auditSort}
                onSortChange={(next) => {
                  setAuditSort(next);
                  setAuditPage(1);
                }}
                onRowClick={(a) => setAuditEntry(a)}
                toolbar={
                  <>
                    <p className="text-xs text-muted">
                      {audit.length} entradas encadenadas por hash. Seleccioná una para ver el detalle.
                    </p>
                  </>
                }
                empty={
                  <EmptyState
                    icon={Fingerprint}
                    title="Sin entradas de auditoría"
                    body="Las acciones de gobierno se encadenan acá a medida que ocurren."
                  />
                }
                footer={
                  sortedAudit.length > 0 ? (
                    <>
                      <ResultCount shown={auditPageRows.length} total={sortedAudit.length} noun="entradas" />
                      {sortedAudit.length > PAGE_SIZE && (
                        <Pagination page={auditPage} pageSize={PAGE_SIZE} total={sortedAudit.length} onPageChange={setAuditPage} />
                      )}
                    </>
                  ) : undefined
                }
              />
            </div>

            <Panel>
              <PanelHeader
                title="Registrar certificación"
                description="Formación del equipo, con vencimiento a la vista."
              />
              <div className="panel-body flex flex-col gap-4">
                <Field label="Miembro">
                  <Input
                    value={certDraft.member_name}
                    onChange={(e) => setCertDraft((d) => ({ ...d, member_name: e.target.value }))}
                    placeholder="Nombre y apellido"
                  />
                </Field>
                <Field label="Certificación">
                  <Select
                    value={certDraft.certification}
                    onChange={(e) => setCertDraft((d) => ({ ...d, certification: e.target.value }))}
                  >
                    {["AI Ethics", "Prompt Safety", "Data Privacy", "Governance"].map((c) => (
                      <option key={c} value={c}>
                        {c}
                      </option>
                    ))}
                  </Select>
                </Field>
                <FormActions>
                  <Button variant="primary" loading={busy === "cert"} disabled={busy !== "" || !certDraft.member_name} onClick={() => void addCert()}>
                    Registrar
                  </Button>
                </FormActions>
              </div>
            </Panel>
          </div>

          <div className="space-y-3">
            <SectionHeader
              eyebrow="Equipo"
              title={`Certificaciones (${certs.length})`}
              description="Las certificaciones vencidas o por vencer en 30 días se marcan en la tabla."
            />
            <DataTable
              columns={CERT_COLUMNS}
              rows={sortedCerts}
              rowKey={(c) => c.id}
              caption="Certificaciones del equipo"
              dense
              sort={certSort}
              onSortChange={setCertSort}
              empty={
                <EmptyState
                  icon={UserCheck}
                  title="Sin certificaciones registradas"
                  body="Registrá la formación del equipo para respaldar el reporte de gobierno."
                  hint="El formulario está arriba, junto a la auditoría."
                />
              }
              footer={sortedCerts.length > 0 ? <ResultCount shown={sortedCerts.length} total={certs.length} noun="certificaciones" /> : undefined}
            />
          </div>

          <div className="space-y-3">
            <SectionHeader
              eyebrow="Políticas"
              title={`Políticas versionadas (${policies.length})`}
              description="Cada política conserva su versión y estado. Seleccioná una para leer el contenido completo."
            />
            <DataTable
              columns={POLICY_COLUMNS}
              rows={sortedPolicies}
              rowKey={(p) => p.id}
              caption="Políticas versionadas"
              stickyHeader
              sort={policySort}
              onSortChange={setPolicySort}
              onRowClick={(p) => setPolicy(p)}
              empty={
                <EmptyState
                  icon={Scales}
                  title="Sin políticas cargadas"
                  body="Las políticas versionadas de la organización aparecen acá con su estado y última actualización."
                />
              }
              footer={sortedPolicies.length > 0 ? <ResultCount shown={sortedPolicies.length} total={policies.length} noun="políticas" /> : undefined}
            />
          </div>
        </>
      )}

      <Drawer
        open={Boolean(policy)}
        onOpenChange={(open) => !open && setPolicy(null)}
        title={policy?.name ?? "Política"}
        description={policy ? `${policy.policy_type} · v${policy.version}` : undefined}
        width={560}
      >
        {policy && (
          <div className="space-y-4">
            <div className="flex flex-wrap items-center gap-2">
              <StatusBadge status={policy.status} />
              <Badge tone="neutral">v{policy.version}</Badge>
              <span className="text-xs text-faint tabular-nums">Actualizada {fmtDateTime(policy.updated_at)}</span>
            </div>
            <div>
              <p className="eyebrow mb-2">Contenido</p>
              <div className="rounded-md border border-border bg-control p-3 text-[13px] leading-relaxed whitespace-pre-wrap text-text">
                {policy.content}
              </div>
            </div>
          </div>
        )}
      </Drawer>

      <Drawer
        open={Boolean(decision)}
        onOpenChange={(open) => !open && setDecision(null)}
        title={decision?.title ?? "Decisión"}
        description={decision?.decision_type}
        width={520}
        footer={
          decision &&
          decision.status === "pending" && (
            <>
              <Button
                variant="danger"
                disabled={busy !== ""}
                onClick={() => decision && setConfirmDecision({ id: decision.id, approve: false })}
              >
                Rechazar
              </Button>
              <Button
                variant="primary"
                leadingIcon={ShieldCheck}
                disabled={busy !== ""}
                onClick={() => decision && setConfirmDecision({ id: decision.id, approve: true })}
              >
                Aprobar con firma
              </Button>
            </>
          )
        }
      >
        {decision && (
          <div className="space-y-4">
            <div className="flex flex-wrap items-center gap-2">
              <DecisionStatusBadge status={decision.status} />
              <Badge tone="neutral">
                {decision.approvers.length}/{decision.required_approvals} firmas
              </Badge>
            </div>
            {decision.rationale && (
              <p className="text-[13px] leading-relaxed text-muted">{decision.rationale}</p>
            )}
            <KeyValue
              columns={2}
              items={[
                { key: "Creada", value: fmtDateTime(decision.created_at) },
                { key: "Decidida", value: decision.decided_at ? fmtDateTime(decision.decided_at) : "Sin decidir" },
                { key: "Objetivo", value: decision.target_id ?? "—", mono: Boolean(decision.target_id) },
              ]}
            />
            <div>
              <p className="eyebrow mb-2">Firmas</p>
              {decision.approvers.length === 0 ? (
                <p className="text-[13px] leading-relaxed text-muted">
                  Sin firmas todavía. Cada aprobación registra nombre, fecha y firma en la auditoría encadenada.
                </p>
              ) : (
                <ul className="flex flex-col gap-2">
                  {decision.approvers.map((a) => (
                    <li key={`${a.user_id}-${a.approved_at}`} className="rounded-sm border border-border-soft bg-raised px-3 py-2">
                      <div className="flex flex-wrap items-center gap-2">
                        <span className="text-[13px] font-medium text-text">{a.name}</span>
                        <Badge tone={a.approved ? "ok" : "danger"} icon={a.approved ? CheckCircle : Prohibit}>
                          {a.approved ? "Aprobó" : "Rechazó"}
                        </Badge>
                        <span className="ml-auto text-[11px] text-faint tabular-nums">{fmtDateTime(a.approved_at)}</span>
                      </div>
                      <p className="mono mt-1 truncate text-[11px] text-faint">{a.signature}</p>
                    </li>
                  ))}
                </ul>
              )}
            </div>
          </div>
        )}
      </Drawer>

      <Drawer
        open={Boolean(auditEntry)}
        onOpenChange={(open) => !open && setAuditEntry(null)}
        title="Entrada de auditoría"
        description={auditEntry ? `${auditEntry.actor_name} · ${auditEntry.action}` : undefined}
        width={520}
      >
        {auditEntry && (
          <div className="space-y-4">
            <KeyValue
              columns={2}
              items={[
                { key: "Entidad", value: auditEntry.entity_type, mono: true },
                { key: "Fecha", value: fmtDateTime(auditEntry.created_at) },
              ]}
            />
            <div>
              <p className="eyebrow mb-2">Detalle</p>
              <p className="text-[13px] leading-relaxed text-muted">{auditEntry.detail}</p>
            </div>
            <div>
              <p className="eyebrow mb-2">Cadena de hash</p>
              <CodeBlock
                code={`hash:      ${auditEntry.hash}\nprev_hash: ${auditEntry.prev_hash || "(sin anterior)"}`}
                language="sha256"
                maxHeight={140}
                actions={<CopyButton value={auditEntry.hash} label="Copiar hash" />}
              />
            </div>
          </div>
        )}
      </Drawer>

      <ConfirmDialog
        open={Boolean(confirmDecision)}
        onOpenChange={(open) => !open && setConfirmDecision(null)}
        title={confirmDecision?.approve ? "Aprobar decisión" : "Rechazar decisión"}
        body="La firma queda registrada en la auditoría encadenada con tu nombre y la fecha. No se puede deshacer."
        confirmLabel={confirmDecision?.approve ? "Aprobar" : "Rechazar"}
        tone={confirmDecision?.approve ? "primary" : "danger"}
        onConfirm={() => {
          if (confirmDecision) void decide(confirmDecision.id, confirmDecision.approve);
          setConfirmDecision(null);
        }}
      />
    </div>
  );
}
