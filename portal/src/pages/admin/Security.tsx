import { CheckCircle, Clock, Question, ShieldCheck } from "@phosphor-icons/react";
import { useEffect, useState } from "react";
import { platformApi } from "../../api";
import { usePlatformAuth } from "../../platformAuth";
import {
  Badge,
  Button,
  DataTable,
  EmptyState,
  ErrorInline,
  Field,
  Input,
  PageHeader,
  Panel,
  PanelHeader,
  PermissionMatrix,
  ResultCount,
  RoleBadge,
  SkeletonBlock,
  SuccessInline,
  type Column,
} from "../../components/ui";

type PlatformUser = {
  id: string;
  email: string | null;
  is_platform_admin: boolean;
  roles: string[];
};

type PlatformRole = {
  id: string;
  name: string;
  description: string | null;
  is_system: boolean;
  permissions: string[];
};

const USER_COLUMNS: Column<PlatformUser>[] = [
  {
    key: "email",
    header: "Email",
    render: (u) => <span className="text-[13px] text-text">{u.email || u.id}</span>,
  },
  {
    key: "roles",
    header: "Roles",
    render: (u) => (
      <span className="inline-flex flex-wrap gap-1">
        {u.roles.length === 0 && <span className="text-xs text-faint">sin rol</span>}
        {u.roles.map((r) => (
          <RoleBadge key={r} role={r} />
        ))}
      </span>
    ),
  },
  {
    key: "legacy",
    header: "Legacy admin",
    render: (u) =>
      u.is_platform_admin ? (
        <Badge tone="ok" icon={CheckCircle}>
          sí
        </Badge>
      ) : (
        <Badge tone="neutral">no</Badge>
      ),
  },
];

/** FASE 07 — panel de MFA del platform admin (TOTP). */
function MfaPanel() {
  const { session } = usePlatformAuth();
  const [status, setStatus] = useState<{ enabled: boolean; pending: boolean } | null>(null);
  const [secret, setSecret] = useState("");
  const [otpAuthUrl, setOtpAuthUrl] = useState("");
  const [code, setCode] = useState("");
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState("");
  const [error, setError] = useState("");

  async function load() {
    if (!session) return;
    try {
      const s = await platformApi<{ enabled: boolean; pending: boolean }>(
        "/api/v1/auth/platform/mfa/status",
        { token: session.token }
      );
      setStatus(s);
      setError("");
    } catch (e) {
      setError(e instanceof Error ? e.message : "Error cargando MFA");
    }
  }

  useEffect(() => {
    void load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [session]);

  async function enroll() {
    if (!session) return;
    setBusy(true);
    setError("");
    setMsg("");
    try {
      const out = await platformApi<{ secret: string; otpauth_url: string }>(
        "/api/v1/auth/platform/mfa/enroll",
        { method: "POST", token: session.token, body: "{}" }
      );
      setSecret(out.secret);
      setOtpAuthUrl(out.otpauth_url);
      setStatus({ enabled: false, pending: true });
    } catch (e) {
      setError(e instanceof Error ? e.message : "Error en enroll");
    } finally {
      setBusy(false);
    }
  }

  async function verify() {
    if (!session) return;
    setBusy(true);
    setError("");
    setMsg("");
    try {
      await platformApi("/api/v1/auth/platform/mfa/verify", {
        method: "POST",
        token: session.token,
        body: JSON.stringify({ code: code.trim() }),
      });
      setSecret("");
      setOtpAuthUrl("");
      setCode("");
      setMsg("MFA habilitado. La próxima sesión de plataforma exigirá tu código.");
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Código inválido");
    } finally {
      setBusy(false);
    }
  }

  async function disable() {
    if (!session) return;
    setBusy(true);
    setError("");
    setMsg("");
    try {
      await platformApi("/api/v1/auth/platform/mfa/disable", {
        method: "POST",
        token: session.token,
        body: "{}",
      });
      setMsg("MFA deshabilitado.");
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Error");
    } finally {
      setBusy(false);
    }
  }

  return (
    <Panel>
      <PanelHeader
        title="MFA (TOTP)"
        description="Protege tu cuenta de plataforma con un autenticador. Las operaciones críticas (impersonar, suspender, cancelar, resetear uso, routing de modelos) requieren MFA reciente."
        actions={
          status?.enabled ? (
            <Badge tone="ok" icon={CheckCircle}>
              Habilitado
            </Badge>
          ) : status?.pending ? (
            <Badge tone="warn" icon={Clock}>
              Pendiente de confirmar
            </Badge>
          ) : (
            <Badge tone="neutral" icon={Question}>
              Deshabilitado
            </Badge>
          )
        }
      />
      <div className="panel-body flex flex-col gap-4">
        {msg && <SuccessInline message={msg} className="mb-0" />}
        {error && <ErrorInline className="mb-0">{error}</ErrorInline>}
        <div className="flex flex-wrap gap-2">
          {!status?.enabled && (
            <Button variant="secondary" loading={busy} onClick={() => void enroll()}>
              Configurar
            </Button>
          )}
          {status?.enabled && (
            <Button variant="ghost" className="text-danger" disabled={busy} onClick={() => void disable()}>
              Deshabilitar
            </Button>
          )}
        </div>
        {otpAuthUrl && (
          <div className="rounded-md border border-border bg-raised p-3">
            <p className="mb-2 text-xs leading-relaxed text-muted">
              Escanea el QR o agrega el secreto manualmente en tu autenticador:
            </p>
            <p className="mono rounded-sm bg-control px-2.5 py-1.5 text-xs break-all text-accent">{secret}</p>
            <div className="mt-3 flex flex-wrap items-end gap-2">
              <Field label="Código de confirmación" className="w-40">
                <Input
                  type="text"
                  inputMode="numeric"
                  value={code}
                  onChange={(e) => setCode(e.target.value.replace(/[^0-9]/g, ""))}
                  className="font-mono"
                  placeholder="123456"
                />
              </Field>
              <Button variant="primary" disabled={busy || !code.trim()} onClick={() => void verify()}>
                Confirmar
              </Button>
            </div>
          </div>
        )}
      </div>
    </Panel>
  );
}

export default function Security() {
  const { session } = usePlatformAuth();
  const [users, setUsers] = useState<PlatformUser[]>([]);
  const [roles, setRoles] = useState<PlatformRole[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  useEffect(() => {
    if (!session) return;
    Promise.all([
      platformApi<{ users: PlatformUser[] }>("/api/v1/platform/users", { token: session.token }),
      platformApi<{ roles: PlatformRole[] }>("/api/v1/platform/roles", { token: session.token }),
    ])
      .then(([u, r]) => {
        setUsers(u.users || []);
        setRoles(r.roles || []);
      })
      .catch((e) => setError(e instanceof Error ? e.message : "Error"))
      .finally(() => setLoading(false));
  }, [session]);

  return (
    <div className="space-y-4">
      <PageHeader
        title="Security"
        subtitle="Usuarios de plataforma, roles granulares y matriz de permisos."
      />
      {error && <ErrorInline>{error}</ErrorInline>}
      {loading ? (
        <SkeletonBlock rows={6} />
      ) : (
        <>
          <MfaPanel />

          <section>
            <div className="mb-3 flex flex-wrap items-end justify-between gap-3">
              <div>
                <h2 className="text-h2">Usuarios de plataforma</h2>
                <p className="mt-1 text-[13px] leading-relaxed text-muted">
                  Cuentas con acceso al Control Center y sus roles asignados.
                </p>
              </div>
            </div>
            <DataTable
              columns={USER_COLUMNS}
              rows={users}
              rowKey={(u) => u.id}
              caption="Usuarios de plataforma"
              stickyHeader
              empty={
                <EmptyState
                  icon={ShieldCheck}
                  title="Sin usuarios"
                  body="No hay usuarios de plataforma registrados."
                />
              }
              footer={users.length > 0 ? <ResultCount shown={users.length} total={users.length} noun="usuarios" /> : undefined}
            />
          </section>

          <section>
            <div className="mb-3">
              <h2 className="text-h2">Matriz de permisos por rol</h2>
              <p className="mt-1 text-[13px] leading-relaxed text-muted">
                Permisos efectivos de cada rol de plataforma: ✓ incluido · · fuera del rol.
              </p>
            </div>
            <Panel>
              <PermissionMatrix roles={roles} />
            </Panel>
          </section>
        </>
      )}
    </div>
  );
}
