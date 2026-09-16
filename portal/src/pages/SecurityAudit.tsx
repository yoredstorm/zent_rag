import {
  CheckCircle,
  Info,
  Key,
  LockKey,
  MagnifyingGlass,
  Minus,
  Prohibit,
  Question,
  Scroll,
  ShieldWarning,
  WarningCircle,
  WarningOctagon,
  type Icon,
} from "@phosphor-icons/react";
import { useEffect, useMemo, useState, type FormEvent } from "react";
import { api } from "../api";
import { useAuth } from "../auth";
import { PageTabs } from "../components/PageTabs";
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
  Modal,
  PageHeader,
  Pagination,
  PasswordInput,
  ResultCount,
  SectionHeader,
  Select,
  SkeletonBlock,
  SuccessInline,
  Switch,
  InfoInline,
  type Column,
  type SortState,
  type Tone,
} from "../components/ui";
import { fmtDateTime } from "../lib/format";

type AuditEntry = {
  action: string;
  resource_type: string;
  resource_id: string | null;
  actor_user_id: string | null;
  ip_address: string | null;
  created_at: string;
};

type AuditRow = AuditEntry & { rowId: string };

type SecurityEvent = {
  id: string;
  event_type: string;
  severity: string;
  score: number;
  status: string;
  evidence: string | null;
  responses: number;
  detected_at: string;
  resolved_at: string | null;
};

type SsoConfig = {
  sso_enabled: boolean;
  issuer: string | null;
  client_id: string | null;
  client_secret_set: boolean;
  roles_claim: string | null;
  scim_enabled: boolean;
  scim_token_prefix: string | null;
  key_max_age_days: number | null;
};

const TABS = [
  { id: "audit", label: "Auditoría", icon: Scroll },
  { id: "events", label: "Eventos de seguridad", icon: ShieldWarning },
  { id: "auth", label: "Autenticación", icon: LockKey },
  { id: "api", label: "Actividad de API", icon: Key },
] as const;

type TabId = (typeof TABS)[number]["id"];

/**
 * Escala única de severidad del bloque de seguridad y riesgo
 * (crítica → alta → media → baja). Mismos valores en SecurityAudit,
 * SecurityCenter y RiskCenter.
 */
const SEVERITY_META: Record<string, { label: string; tone: Tone; icon: Icon }> = {
  critical: { label: "Crítica", tone: "danger", icon: WarningOctagon },
  high: { label: "Alta", tone: "warn", icon: WarningCircle },
  medium: { label: "Media", tone: "info", icon: Info },
  low: { label: "Baja", tone: "neutral", icon: Minus },
  info: { label: "Informativa", tone: "neutral", icon: Info },
};

function SeverityBadge({ severity }: { severity: string }) {
  const meta = SEVERITY_META[severity] ?? {
    label: severity || "Sin dato",
    tone: "neutral" as Tone,
    icon: Question,
  };
  return (
    <Badge tone={meta.tone} icon={meta.icon}>
      {meta.label}
    </Badge>
  );
}

/**
 * Estados de eventos SOC: no están en STATUS_META (components/ui/Badge.tsx,
 * fuera del alcance de esta fase). Mismos valores en SecurityCenter.
 */
const SOC_STATUS_META: Record<string, { label: string; tone: Tone; icon: Icon }> = {
  detected: { label: "Detectado", tone: "danger", icon: WarningOctagon },
  contained: { label: "Contenido", tone: "warn", icon: ShieldWarning },
  resolved: { label: "Resuelto", tone: "ok", icon: CheckCircle },
  false_positive: { label: "Falso positivo", tone: "neutral", icon: Prohibit },
};

function SocStatusBadge({ status }: { status: string }) {
  const meta = SOC_STATUS_META[status] ?? {
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

function prettyJson(value: unknown): string {
  try {
    return JSON.stringify(value, null, 2);
  } catch {
    return String(value);
  }
}

function prettyJsonText(value: string | null): string {
  if (!value) return "—";
  try {
    return JSON.stringify(JSON.parse(value), null, 2);
  } catch {
    return value;
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

const AUDIT_COLUMNS: Column<AuditRow>[] = [
  {
    key: "action",
    header: "Acción",
    sortable: true,
    render: (e) => <span className="mono text-xs text-text">{e.action}</span>,
  },
  {
    key: "resource_type",
    header: "Recurso",
    sortable: true,
    hideBelow: "md",
    render: (e) => (
      <span className="text-xs text-muted">
        {e.resource_type}
        {e.resource_id && <span className="mono text-faint"> · {e.resource_id.slice(0, 12)}…</span>}
      </span>
    ),
  },
  {
    key: "actor_user_id",
    header: "Actor",
    sortable: true,
    hideBelow: "lg",
    render: (e) => (
      <span className="mono text-xs text-faint">
        {e.actor_user_id ? `${e.actor_user_id.slice(0, 8)}…` : "system"}
      </span>
    ),
  },
  {
    key: "ip_address",
    header: "IP",
    hideBelow: "xl",
    render: (e) => <span className="mono text-xs text-faint">{e.ip_address ?? "—"}</span>,
  },
  {
    key: "created_at",
    header: "Fecha",
    sortable: true,
    align: "right",
    render: (e) => <span className="text-xs text-muted tabular-nums">{fmtDateTime(e.created_at)}</span>,
  },
];

const EVENT_COLUMNS: Column<SecurityEvent>[] = [
  {
    key: "event_type",
    header: "Evento",
    sortable: true,
    render: (ev) => <span className="mono text-xs text-text">{ev.event_type}</span>,
  },
  {
    key: "severity",
    header: "Severidad",
    sortable: true,
    render: (ev) => <SeverityBadge severity={ev.severity} />,
  },
  {
    key: "score",
    header: "Score",
    sortable: true,
    align: "right",
    render: (ev) => <span className="mono text-xs text-muted">{Math.round(ev.score)}</span>,
  },
  {
    key: "status",
    header: "Estado",
    sortable: true,
    render: (ev) => <SocStatusBadge status={ev.status} />,
  },
  {
    key: "detected_at",
    header: "Detectado",
    sortable: true,
    hideBelow: "md",
    render: (ev) => <span className="text-xs text-muted tabular-nums">{fmtDateTime(ev.detected_at)}</span>,
  },
];

const AUDIT_PAGE_SIZE = 25;

export default function SecurityAuditPage() {
  const { session } = useAuth();
  const [tab, setTab] = useState<TabId>("audit");
  const [entries, setEntries] = useState<AuditEntry[]>([]);
  const [events, setEvents] = useState<SecurityEvent[]>([]);
  const [loadingAudit, setLoadingAudit] = useState(true);
  const [loadingEvents, setLoadingEvents] = useState(true);
  const [error, setError] = useState("");
  const [auditSort, setAuditSort] = useState<SortState>({ key: "created_at", dir: "desc" });
  const [eventSort, setEventSort] = useState<SortState>({ key: "detected_at", dir: "desc" });
  const [query, setQuery] = useState("");
  const [resourceFilter, setResourceFilter] = useState("");
  const [severityFilter, setSeverityFilter] = useState("");
  const [page, setPage] = useState(1);
  const [auditDetail, setAuditDetail] = useState<AuditEntry | null>(null);
  const [eventDetail, setEventDetail] = useState<SecurityEvent | null>(null);

  useEffect(() => {
    if (!session) return;
    setLoadingAudit(true);
    api<{ entries: AuditEntry[] }>("/api/v1/audit-logs?limit=200", {
      token: session.token,
      organizationId: session.organizationId,
    })
      .then((data) => setEntries(data.entries || []))
      .catch((err) => setError(err instanceof Error ? err.message : "Error"))
      .finally(() => setLoadingAudit(false));
  }, [session]);

  useEffect(() => {
    if (!session) return;
    setLoadingEvents(true);
    api<{ events: SecurityEvent[] }>("/api/v1/soc/events", {
      token: session.token,
      organizationId: session.organizationId,
    })
      .catch(() => ({ events: [] as SecurityEvent[] }))
      .then((data) => setEvents(data.events || []))
      .finally(() => setLoadingEvents(false));
  }, [session]);

  const auditRows = useMemo<AuditRow[]>(
    () => entries.map((e, i) => ({ ...e, rowId: `${e.created_at}-${e.action}-${i}` })),
    [entries],
  );

  const resourceTypes = useMemo(
    () => Array.from(new Set(entries.map((e) => e.resource_type))).sort(),
    [entries],
  );

  const severities = useMemo(
    () => Array.from(new Set(events.map((e) => e.severity))).sort(),
    [events],
  );

  const filteredAudit = useMemo(() => {
    const term = query.trim().toLowerCase();
    return auditRows.filter((e) => {
      if (resourceFilter && e.resource_type !== resourceFilter) return false;
      if (!term) return true;
      return [e.action, e.resource_type, e.resource_id ?? "", e.actor_user_id ?? "", e.ip_address ?? ""]
        .join(" ")
        .toLowerCase()
        .includes(term);
    });
  }, [auditRows, query, resourceFilter]);

  const auditSorted = useMemo(() => applySort(filteredAudit, auditSort), [filteredAudit, auditSort]);
  const auditPage = auditSorted.slice((page - 1) * AUDIT_PAGE_SIZE, page * AUDIT_PAGE_SIZE);

  const eventRows = useMemo(
    () => applySort(severityFilter ? events.filter((e) => e.severity === severityFilter) : events, eventSort),
    [events, eventSort, severityFilter],
  );

  return (
    <div>
      <PageHeader
        title="Seguridad y Auditoría"
        subtitle="Actividad sensible del workspace y eventos de seguridad detectados por la plataforma."
      />
      <PageTabs tabs={TABS} active={tab} onChange={(id) => setTab(id as TabId)} idPrefix="sec" />
      <ErrorInline message={error} />

      {tab === "audit" && (
        <div className="mt-4 space-y-3" role="tabpanel" id="sec-panel-audit" aria-labelledby="sec-audit">
          <SectionHeader
            eyebrow="Auditoría"
            title="Eventos auditados"
            description="Cada acción sensible queda registrada con actor, recurso e IP de origen. Seleccioná una fila para inspeccionar la evidencia."
            actions={<Badge tone="neutral">{auditRows.length} registros</Badge>}
          />
          <DataTable
            columns={AUDIT_COLUMNS}
            rows={auditPage}
            rowKey={(e) => e.rowId}
            caption="Eventos auditados"
            loading={loadingAudit}
            stickyHeader
            sort={auditSort}
            onSortChange={(next) => {
              setAuditSort(next);
              setPage(1);
            }}
            onRowClick={(e) => setAuditDetail(e)}
            toolbar={
              <>
                <Input
                  className="w-full sm:w-64"
                  icon={MagnifyingGlass}
                  aria-label="Buscar en eventos auditados"
                  placeholder="Buscar acción, recurso o actor"
                  value={query}
                  onChange={(e) => {
                    setQuery(e.target.value);
                    setPage(1);
                  }}
                />
                {resourceTypes.length > 1 && (
                  <Select
                    className="w-full sm:w-52"
                    aria-label="Filtrar por tipo de recurso"
                    placeholder="Todos los recursos"
                    value={resourceFilter}
                    onChange={(e) => {
                      setResourceFilter(e.target.value);
                      setPage(1);
                    }}
                  >
                    {resourceTypes.map((type) => (
                      <option key={type} value={type}>
                        {type}
                      </option>
                    ))}
                  </Select>
                )}
              </>
            }
            empty={
              <EmptyState
                icon={Scroll}
                title={entries.length === 0 ? "Sin actividad auditada" : "Sin coincidencias"}
                body={
                  entries.length === 0
                    ? "El registro está vacío: todavía no se registraron cambios de claves, accesos, políticas ni datos."
                    : "Ningún evento coincide con la búsqueda y el filtro activos."
                }
                hint={entries.length === 0 ? "Los eventos aparecen acá automáticamente." : undefined}
              />
            }
            footer={
              auditSorted.length > 0 ? (
                <>
                  <ResultCount shown={auditPage.length} total={auditSorted.length} noun="eventos" />
                  {auditSorted.length > AUDIT_PAGE_SIZE && (
                    <Pagination
                      page={page}
                      pageSize={AUDIT_PAGE_SIZE}
                      total={auditSorted.length}
                      onPageChange={setPage}
                    />
                  )}
                </>
              ) : undefined
            }
          />
        </div>
      )}

      {tab === "events" && (
        <div className="mt-4 space-y-3" role="tabpanel" id="sec-panel-events" aria-labelledby="sec-events">
          <SectionHeader
            eyebrow="Detección"
            title="Eventos de seguridad"
            description="Hallazgos del motor de detección, con severidad, score y estado. Seleccioná una fila para ver la evidencia cruda."
            actions={<Badge tone="neutral">{events.length} eventos</Badge>}
          />
          <DataTable
            columns={EVENT_COLUMNS}
            rows={eventRows}
            rowKey={(ev) => ev.id}
            caption="Eventos de seguridad"
            loading={loadingEvents}
            stickyHeader
            sort={eventSort}
            onSortChange={setEventSort}
            onRowClick={(ev) => setEventDetail(ev)}
            toolbar={
              severities.length > 1 ? (
                <Select
                  className="w-full sm:w-52"
                  aria-label="Filtrar por severidad"
                  placeholder="Todas las severidades"
                  value={severityFilter}
                  onChange={(e) => setSeverityFilter(e.target.value)}
                >
                  {severities.map((s) => (
                    <option key={s} value={s}>
                      {SEVERITY_META[s]?.label ?? s}
                    </option>
                  ))}
                </Select>
              ) : undefined
            }
            empty={
              <EmptyState
                icon={ShieldWarning}
                title={events.length === 0 ? "Sin eventos de seguridad" : "Sin coincidencias"}
                body={
                  events.length === 0
                    ? "El motor de detección no registró actividad sospechosa en esta organización."
                    : "Ningún evento coincide con la severidad seleccionada."
                }
                hint={
                  events.length === 0
                    ? "Los eventos aparecen acá cuando el motor los detecta; no requiere acción tuya."
                    : undefined
                }
              />
            }
            footer={<ResultCount shown={eventRows.length} total={events.length} noun="eventos" />}
          />
        </div>
      )}

      {tab === "auth" && (
        <div role="tabpanel" id="sec-panel-auth" aria-labelledby="sec-auth">
          <AuthConfigPanel session={session} />
        </div>
      )}

      {tab === "api" && (
        <div className="mt-4" role="tabpanel" id="sec-panel-api" aria-labelledby="sec-api">
          <div className="panel">
            <EmptyState
              icon={Key}
              title="Actividad por clave todavía no disponible"
              body="El registro detallado de uso por credencial llega en una próxima entrega. Mientras tanto, cada llamada autenticada queda en la pestaña Auditoría."
              action={<Button variant="secondary" onClick={() => setTab("audit")}>Ver auditoría</Button>}
            />
          </div>
        </div>
      )}

      <Drawer
        open={Boolean(auditDetail)}
        onOpenChange={(open) => !open && setAuditDetail(null)}
        title="Evento auditado"
        description={auditDetail?.action}
        width={520}
      >
        {auditDetail && (
          <div className="space-y-4">
            <KeyValue
              columns={2}
              items={[
                { key: "Acción", value: auditDetail.action, mono: true },
                { key: "Recurso", value: `${auditDetail.resource_type}${auditDetail.resource_id ? ` · ${auditDetail.resource_id}` : ""}`, mono: true },
                { key: "Actor", value: auditDetail.actor_user_id ?? "system", mono: true },
                { key: "IP de origen", value: auditDetail.ip_address ?? "—", mono: true },
                { key: "Fecha", value: fmtDateTime(auditDetail.created_at) },
              ]}
            />
            <div>
              <p className="eyebrow mb-2">Evidencia cruda</p>
              <CodeBlock code={prettyJson(auditDetail)} language="json" maxHeight={320} />
            </div>
          </div>
        )}
      </Drawer>

      <Drawer
        open={Boolean(eventDetail)}
        onOpenChange={(open) => !open && setEventDetail(null)}
        title="Evento de seguridad"
        description={eventDetail?.event_type}
        width={520}
      >
        {eventDetail && (
          <div className="space-y-4">
            <div className="flex flex-wrap items-center gap-2">
              <SeverityBadge severity={eventDetail.severity} />
              <SocStatusBadge status={eventDetail.status} />
              <Badge tone="neutral">Score {Math.round(eventDetail.score)}</Badge>
            </div>
            <KeyValue
              columns={2}
              items={[
                { key: "Tipo", value: eventDetail.event_type, mono: true },
                { key: "Detectado", value: fmtDateTime(eventDetail.detected_at) },
                { key: "Resuelto", value: eventDetail.resolved_at ? fmtDateTime(eventDetail.resolved_at) : "Sin resolver" },
                { key: "Respuestas registradas", value: String(eventDetail.responses) },
              ]}
            />
            <div>
              <p className="eyebrow mb-2">Evidencia</p>
              <CodeBlock code={prettyJsonText(eventDetail.evidence)} language="json" maxHeight={320} />
            </div>
          </div>
        )}
      </Drawer>
    </div>
  );
}

/** Configuración real de autenticación: SSO, SCIM y política de claves (Fase 17). */
function AuthConfigPanel({ session }: { session: ReturnType<typeof useAuth>["session"] }) {
  const [cfg, setCfg] = useState<SsoConfig | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [msg, setMsg] = useState("");
  const [busy, setBusy] = useState("");
  const [form, setForm] = useState({
    enabled: false,
    issuer: "",
    client_id: "",
    client_secret: "",
    roles_claim: "roles",
  });
  const [keyDays, setKeyDays] = useState("");
  const [scimToken, setScimToken] = useState("");
  const [confirm, setConfirm] = useState<"disable_sso" | "scim_create" | "scim_revoke" | null>(null);

  async function load() {
    if (!session) return;
    setLoading(true);
    setError("");
    try {
      const data = await api<SsoConfig>("/api/v1/auth/sso/config", {
        token: session.token,
        organizationId: session.organizationId,
      });
      setCfg(data);
      setForm({
        enabled: data.sso_enabled,
        issuer: data.issuer || "",
        client_id: data.client_id || "",
        client_secret: "",
        roles_claim: data.roles_claim || "roles",
      });
      setKeyDays(data.key_max_age_days != null ? String(data.key_max_age_days) : "");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Error cargando configuración");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    void load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [session]);

  async function saveSso() {
    if (!session) return;
    setBusy("sso");
    setError("");
    setMsg("");
    try {
      await api("/api/v1/auth/sso/config", {
        method: "PUT",
        token: session.token,
        organizationId: session.organizationId,
        body: JSON.stringify({
          enabled: form.enabled,
          issuer: form.issuer.trim() || null,
          client_id: form.client_id.trim() || null,
          client_secret: form.client_secret.trim() || null,
          roles_claim: form.roles_claim.trim() || "roles",
        }),
      });
      setMsg("Configuración SSO guardada.");
      setForm((f) => ({ ...f, client_secret: "" }));
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Error al guardar SSO");
    } finally {
      setBusy("");
    }
  }

  async function testSso() {
    if (!session) return;
    setBusy("test");
    setError("");
    setMsg("");
    try {
      const out = await api<{ status: string; authorization_endpoint?: string }>(
        "/api/v1/auth/sso/test",
        {
          method: "POST",
          token: session.token,
          organizationId: session.organizationId,
          body: JSON.stringify({ enabled: form.enabled, issuer: form.issuer.trim(), client_id: form.client_id.trim(), roles_claim: form.roles_claim }),
        }
      );
      setMsg(out.status === "ok" ? "IdP accesible." : "No se pudo contactar el IdP.");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Error probando SSO");
    } finally {
      setBusy("");
    }
  }

  async function generateScim() {
    if (!session) return;
    setBusy("scim");
    setError("");
    setMsg("");
    try {
      const out = await api<{ token: string }>("/api/v1/auth/sso/scim-token", {
        method: "POST",
        token: session.token,
        organizationId: session.organizationId,
      });
      setScimToken(out.token);
      setMsg("Token SCIM generado. Cópialo ahora; no se vuelve a mostrar.");
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Error generando token SCIM");
    } finally {
      setBusy("");
    }
  }

  async function revokeScim() {
    if (!session) return;
    setBusy("scim-del");
    setError("");
    setMsg("");
    try {
      await api("/api/v1/auth/sso/scim-token", {
        method: "DELETE",
        token: session.token,
        organizationId: session.organizationId,
      });
      setScimToken("");
      setMsg("SCIM deshabilitado.");
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Error deshabilitando SCIM");
    } finally {
      setBusy("");
    }
  }

  async function saveKeyPolicy() {
    if (!session) return;
    setBusy("keys");
    setError("");
    setMsg("");
    try {
      const days = keyDays.trim() === "" ? null : Number(keyDays.trim());
      await api("/api/v1/auth/sso/key-policy", {
        method: "PUT",
        token: session.token,
        organizationId: session.organizationId,
        body: JSON.stringify({ max_age_days: days }),
      });
      setMsg("Política de expiración guardada.");
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Error guardando política");
    } finally {
      setBusy("");
    }
  }

  function submitSso(e: FormEvent) {
    e.preventDefault();
    if (cfg?.sso_enabled && !form.enabled) {
      setConfirm("disable_sso");
      return;
    }
    void saveSso();
  }

  if (loading) {
    return (
      <div className="mt-4 panel">
        <div className="panel-body">
          <SkeletonBlock rows={5} />
        </div>
      </div>
    );
  }

  return (
    <div className="mt-4 space-y-4">
      <ErrorInline message={error} className="mb-0" />
      <SuccessInline message={msg} className="mb-0" />

      <div className="grid gap-4 lg:grid-cols-2">
        <section className="panel">
          <div className="panel-header">
            <div className="min-w-0">
              <h2 className="text-h3 flex items-center gap-2">
                <LockKey size={15} aria-hidden /> SSO (OIDC)
              </h2>
              <p className="mt-0.5 text-xs leading-relaxed text-muted">
                Ingreso con tu proveedor de identidad. Los secretos se guardan cifrados y no se vuelven a mostrar.
              </p>
            </div>
            <Badge tone={form.enabled ? "ok" : "neutral"} icon={form.enabled ? CheckCircle : undefined}>
              {form.enabled ? "Habilitado" : "Deshabilitado"}
            </Badge>
          </div>
          <form className="panel-body flex flex-col gap-4" onSubmit={submitSso}>
            <Switch
              checked={form.enabled}
              onCheckedChange={(enabled) => setForm((f) => ({ ...f, enabled }))}
              label="Habilitar SSO"
              hint="Cuando está activo, los miembros inician sesión con el IdP."
            />
            <Field label="Issuer" hint="URL base del proveedor; se usa para descubrir los endpoints OIDC.">
              <Input
                value={form.issuer}
                onChange={(e) => setForm((f) => ({ ...f, issuer: e.target.value }))}
                placeholder="https://idp.example.com"
                autoComplete="off"
              />
            </Field>
            <Field label="Client ID">
              <Input
                value={form.client_id}
                onChange={(e) => setForm((f) => ({ ...f, client_id: e.target.value }))}
                autoComplete="off"
              />
            </Field>
            <Field
              label="Client Secret"
              hint={cfg?.client_secret_set ? "Ya hay un secreto guardado: dejalo vacío para conservarlo." : undefined}
            >
              <PasswordInput
                value={form.client_secret}
                onChange={(e) => setForm((f) => ({ ...f, client_secret: e.target.value }))}
                placeholder={cfg?.client_secret_set ? "Sin cambios" : ""}
                autoComplete="new-password"
              />
            </Field>
            <Field label="Claim de roles" hint="Claim del IdP que trae los roles de la organización.">
              <Input
                value={form.roles_claim}
                onChange={(e) => setForm((f) => ({ ...f, roles_claim: e.target.value }))}
              />
            </Field>
            <FormActions>
              <Button
                type="button"
                variant="secondary"
                onClick={() => void testSso()}
                disabled={busy !== "" || !form.issuer.trim()}
                loading={busy === "test"}
              >
                Probar IdP
              </Button>
              <Button type="submit" variant="primary" disabled={busy !== ""} loading={busy === "sso"}>
                Guardar
              </Button>
            </FormActions>
          </form>
        </section>

        <section className="panel">
          <div className="panel-header">
            <div className="min-w-0">
              <h2 className="text-h3 flex items-center gap-2">
                <Key size={15} aria-hidden /> SCIM provisioning
              </h2>
              <p className="mt-0.5 text-xs leading-relaxed text-muted">
                Endpoint{" "}
                <code className="rounded-xs bg-soft px-1 py-0.5 font-mono text-xs text-accent">/api/v1/scim/v2</code>{" "}
                con token Bearer.
              </p>
            </div>
            <Badge tone={cfg?.scim_enabled ? "ok" : "neutral"} icon={cfg?.scim_enabled ? CheckCircle : undefined}>
              {cfg?.scim_enabled ? "Habilitado" : "Deshabilitado"}
            </Badge>
          </div>
          <div className="panel-body space-y-3">
            {scimToken ? (
              <InfoInline
                className="mb-0"
                message="El token se mostró una sola vez. Si lo perdiste, generá uno nuevo."
              />
            ) : (
              <p className="text-[13px] leading-relaxed text-muted">
                El token se muestra una sola vez al generarlo. Si ya hay uno activo, dejá de funcionar al reemplazarlo.
              </p>
            )}
            <div className="flex flex-wrap gap-2">
              <Button
                variant="secondary"
                disabled={busy !== ""}
                loading={busy === "scim"}
                onClick={() => setConfirm("scim_create")}
              >
                Generar token
              </Button>
              {cfg?.scim_enabled && (
                <Button
                  variant="ghost"
                  className="text-danger"
                  disabled={busy !== ""}
                  loading={busy === "scim-del"}
                  onClick={() => setConfirm("scim_revoke")}
                >
                  Deshabilitar SCIM
                </Button>
              )}
            </div>
          </div>

          <div className="border-t border-border px-4 py-3">
            <h2 className="text-h3 flex items-center gap-2">
              <Key size={15} aria-hidden /> Política de API keys
            </h2>
            <p className="mt-0.5 text-xs leading-relaxed text-muted">
              Expiración forzada: las claves más antiguas que el límite se rechazan automáticamente.
            </p>
          </div>
          <div className="panel-body pt-3">
            <div className="flex flex-wrap items-end gap-3">
              <Field
                className="w-40"
                label="Máx. edad (días)"
                hint="Vacío: sin expiración forzada."
              >
                <Input
                  type="number"
                  min={1}
                  max={3650}
                  value={keyDays}
                  onChange={(e) => setKeyDays(e.target.value)}
                  placeholder="Ej. 90"
                />
              </Field>
              <Button
                variant="secondary"
                disabled={busy !== ""}
                loading={busy === "keys"}
                onClick={() => void saveKeyPolicy()}
              >
                Guardar política
              </Button>
            </div>
          </div>
        </section>
      </div>

      <Modal
        open={Boolean(scimToken)}
        onOpenChange={(open) => !open && setScimToken("")}
        title="Token SCIM"
        description="Copialo ahora: no se vuelve a mostrar."
        size="md"
        footer={
          <Button variant="secondary" onClick={() => setScimToken("")}>
            Cerrar
          </Button>
        }
      >
        <CodeBlock
          code={scimToken}
          language="bearer"
          maxHeight={160}
          actions={<CopyButton value={scimToken} />}
        />
      </Modal>

      <ConfirmDialog
        open={confirm === "disable_sso"}
        onOpenChange={(open) => !open && setConfirm(null)}
        title="Desactivar SSO"
        body="Los miembros que ingresan con el IdP dejan de poder iniciar sesión por ese camino hasta que lo reactives."
        confirmLabel="Desactivar SSO"
        onConfirm={() => {
          setConfirm(null);
          void saveSso();
        }}
      />

      <ConfirmDialog
        open={confirm === "scim_create"}
        onOpenChange={(open) => !open && setConfirm(null)}
        title="Generar token SCIM"
        body="Si ya hay un token activo, deja de funcionar en cuanto se emite el nuevo."
        confirmLabel="Generar token"
        tone="primary"
        onConfirm={() => {
          setConfirm(null);
          void generateScim();
        }}
      />

      <ConfirmDialog
        open={confirm === "scim_revoke"}
        onOpenChange={(open) => !open && setConfirm(null)}
        title="Deshabilitar SCIM"
        body="Tu IdP deja de sincronizar usuarios y grupos con esta organización."
        confirmLabel="Deshabilitar"
        onConfirm={() => {
          setConfirm(null);
          void revokeScim();
        }}
      />
    </div>
  );
}
