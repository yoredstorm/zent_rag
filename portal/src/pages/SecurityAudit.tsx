import { Key, LockKey, Scroll, ShieldWarning } from "@phosphor-icons/react";
import { FormEvent, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api";
import { useAuth } from "../auth";
import { ComingSoon } from "../components/ComingSoon";
import { PageTabs } from "../components/PageTabs";
import {
  EmptyState,
  ErrorInline,
  PageHeader,
  SkeletonBlock,
  Spinner,
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

const SEVERITY_TONES: Record<string, string> = {
  critical: "badge-danger",
  high: "badge-danger",
  medium: "badge-pending",
  low: "badge-muted",
  info: "badge-muted",
};

export default function SecurityAuditPage() {
  const { session } = useAuth();
  const [tab, setTab] = useState<TabId>("audit");
  const [entries, setEntries] = useState<AuditEntry[]>([]);
  const [events, setEvents] = useState<SecurityEvent[]>([]);
  const [loadingAudit, setLoadingAudit] = useState(true);
  const [loadingEvents, setLoadingEvents] = useState(true);
  const [error, setError] = useState("");

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

  return (
    <div>
      <PageHeader
        title="Seguridad y Auditoría"
        subtitle="Revisa la actividad sensible de tu workspace y los eventos de seguridad detectados por la plataforma."
      />
      <PageTabs tabs={TABS} active={tab} onChange={(id) => setTab(id as TabId)} idPrefix="sec" />
      <ErrorInline message={error} />

      {tab === "audit" && (
        <div className="panel mt-4">
          <div className="flex items-center gap-2 border-b border-border px-5 py-4">
            <Scroll size={16} className="text-accent" aria-hidden />
            <h2 className="text-sm font-semibold text-text">Eventos auditados ({entries.length})</h2>
          </div>
          {loadingAudit ? (
            <div className="p-5">
              <SkeletonBlock rows={6} />
            </div>
          ) : entries.length === 0 ? (
            <EmptyState
              icon={Scroll}
              title="Sin eventos"
              body="Aún no hay acciones auditadas para esta organización."
            />
          ) : (
            <div className="divide-y divide-border">
              {entries.map((e, i) => (
                <div key={`${e.action}-${e.created_at}-${i}`} className="flex flex-col gap-1 px-5 py-3">
                  <div className="flex flex-wrap items-center gap-2">
                    <span className="badge badge-pending">{e.action}</span>
                    <span className="text-xs text-faint">
                      {e.resource_type}
                      {e.resource_id ? ` · ${e.resource_id.slice(0, 12)}…` : ""}
                    </span>
                    <span className="ml-auto text-xs text-faint">{fmtDateTime(e.created_at)}</span>
                  </div>
                  {(e.ip_address || e.actor_user_id) && (
                    <span className="mono text-xs text-faint">
                      actor={e.actor_user_id?.slice(0, 8) ?? "system"} ip={e.ip_address ?? "—"}
                    </span>
                  )}
                </div>
              ))}
            </div>
          )}
        </div>
      )}

      {tab === "events" && (
        <div className="panel mt-4">
          <div className="flex items-center gap-2 border-b border-border px-5 py-4">
            <ShieldWarning size={16} className="text-accent" aria-hidden />
            <h2 className="text-sm font-semibold text-text">Eventos de seguridad ({events.length})</h2>
          </div>
          {loadingEvents ? (
            <div className="p-5">
              <SkeletonBlock rows={6} />
            </div>
          ) : events.length === 0 ? (
            <EmptyState
              icon={ShieldWarning}
              title="Sin eventos de seguridad"
              body="La plataforma monitorea actividad sospechosa y responderá aquí cuando la detecte."
            />
          ) : (
            <div className="overflow-x-auto">
              <table className="table min-w-[680px]">
                <thead>
                  <tr>
                    <th>Evento</th>
                    <th>Severidad</th>
                    <th>Score</th>
                    <th>Estado</th>
                    <th>Detectado</th>
                  </tr>
                </thead>
                <tbody>
                  {events.map((ev) => (
                    <tr key={ev.id}>
                      <td className="mono text-xs text-text">{ev.event_type}</td>
                      <td>
                        <span className={`badge ${SEVERITY_TONES[ev.severity] || "badge-muted"}`}>
                          {ev.severity}
                        </span>
                      </td>
                      <td className="mono text-xs">{Math.round(ev.score)}</td>
                      <td>
                        <span className="badge badge-muted">{ev.status}</span>
                      </td>
                      <td className="text-xs text-faint">{fmtDateTime(ev.detected_at)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      )}

      {tab === "auth" && <AuthConfigPanel session={session} />}

      {tab === "api" && (
        <div className="mt-4">
          <ComingSoon>
            <Link to="/keys" className="text-accent underline underline-offset-2">
              Administra tus credenciales en API y Claves.
            </Link>{" "}
            El registro detallado de actividad por clave llegará en una próxima fase.
          </ComingSoon>
        </div>
      )}
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

  async function saveSso(e: FormEvent) {
    e.preventDefault();
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

  if (loading) {
    return (
      <div className="mt-4">
        <SkeletonBlock rows={5} />
      </div>
    );
  }

  return (
    <div className="mt-4 grid gap-4 lg:grid-cols-2">
      <ErrorInline message={error} />
      {msg && (
        <div className="rounded-md border border-ok/25 bg-ok-soft px-3 py-2.5 text-sm text-ok" role="status">
          {msg}
        </div>
      )}

      <section className="panel p-5">
        <h2 className="flex items-center gap-2 text-sm font-semibold text-text">
          <LockKey size={15} aria-hidden /> SSO (OIDC)
        </h2>
        <p className="mt-1 mb-3 text-[13px] text-muted">
          Inicia sesión con tu proveedor de identidad. La configuración se guarda cifrada.
        </p>
        <form className="flex flex-col gap-3" onSubmit={(e) => void saveSso(e)}>
          <label className="flex min-h-11 items-center gap-2 text-sm text-text">
            <input
              type="checkbox"
              checked={form.enabled}
              onChange={(e) => setForm((f) => ({ ...f, enabled: e.target.checked }))}
            />
            Habilitar SSO
          </label>
          <label className="block text-sm text-text">
            Issuer
            <input
              className="mt-1 w-full min-h-11 rounded-md border border-border bg-soft px-3 py-2 text-sm"
              value={form.issuer}
              onChange={(e) => setForm((f) => ({ ...f, issuer: e.target.value }))}
              placeholder="https://idp.example.com"
            />
          </label>
          <label className="block text-sm text-text">
            Client ID
            <input
              className="mt-1 w-full min-h-11 rounded-md border border-border bg-soft px-3 py-2 text-sm"
              value={form.client_id}
              onChange={(e) => setForm((f) => ({ ...f, client_id: e.target.value }))}
            />
          </label>
          <label className="block text-sm text-text">
            Client Secret {cfg?.client_secret_set && <span className="badge badge-ok">configurado</span>}
            <input
              type="password"
              className="mt-1 w-full min-h-11 rounded-md border border-border bg-soft px-3 py-2 text-sm"
              value={form.client_secret}
              onChange={(e) => setForm((f) => ({ ...f, client_secret: e.target.value }))}
              placeholder={cfg?.client_secret_set ? "Dejar vacío para conservarlo" : ""}
            />
          </label>
          <label className="block text-sm text-text">
            Claim de roles
            <input
              className="mt-1 w-full min-h-11 rounded-md border border-border bg-soft px-3 py-2 text-sm"
              value={form.roles_claim}
              onChange={(e) => setForm((f) => ({ ...f, roles_claim: e.target.value }))}
            />
          </label>
          <div className="flex flex-wrap gap-2">
            <button type="submit" className="btn btn-primary min-h-10" disabled={busy !== ""}>
              {busy === "sso" ? <Spinner size={14} /> : "Guardar"}
            </button>
            <button
              type="button"
              className="btn btn-secondary min-h-10"
              disabled={busy !== "" || !form.issuer.trim()}
              onClick={() => void testSso()}
            >
              {busy === "test" ? <Spinner size={14} /> : "Probar IdP"}
            </button>
          </div>
        </form>
      </section>

      <section className="panel p-5">
        <h2 className="flex items-center gap-2 text-sm font-semibold text-text">
          <Key size={15} aria-hidden /> SCIM provisioning
        </h2>
        <p className="mt-1 mb-3 text-[13px] text-muted">
          Endpoint <code className="rounded-xs bg-soft px-1 py-0.5 font-mono text-xs text-accent">/api/v1/scim/v2</code>{" "}
          con token Bearer. Estado:{" "}
          {cfg?.scim_enabled ? (
            <span className="badge badge-ok">habilitado</span>
          ) : (
            <span className="badge badge-muted">deshabilitado</span>
          )}
        </p>
        {scimToken && (
          <p className="mb-3 break-all rounded-md border border-border bg-soft p-3 font-mono text-xs text-accent">
            {scimToken}
          </p>
        )}
        <div className="flex flex-wrap gap-2">
          <button type="button" className="btn btn-secondary min-h-10" disabled={busy !== ""} onClick={() => void generateScim()}>
            {busy === "scim" ? <Spinner size={14} /> : "Generar token"}
          </button>
          {cfg?.scim_enabled && (
            <button type="button" className="btn btn-ghost min-h-10 text-danger" disabled={busy !== ""} onClick={() => void revokeScim()}>
              Deshabilitar SCIM
            </button>
          )}
        </div>

        <h2 className="mt-6 flex items-center gap-2 text-sm font-semibold text-text">
          <Key size={15} aria-hidden /> Política de API keys
        </h2>
        <p className="mt-1 mb-3 text-[13px] text-muted">
          Expiración forzada: las claves con más de N días se rechazan automáticamente.
        </p>
        <div className="flex flex-wrap items-end gap-2">
          <label className="block text-sm text-text">
            Máx. edad (días)
            <input
              type="number"
              min={1}
              max={3650}
              className="mt-1 w-36 min-h-11 rounded-md border border-border bg-soft px-3 py-2 text-sm"
              value={keyDays}
              onChange={(e) => setKeyDays(e.target.value)}
              placeholder="Ej. 90"
            />
          </label>
          <button type="button" className="btn btn-secondary min-h-11" disabled={busy !== ""} onClick={() => void saveKeyPolicy()}>
            {busy === "keys" ? <Spinner size={14} /> : "Guardar política"}
          </button>
        </div>
      </section>
    </div>
  );
}