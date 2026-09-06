import { ShieldCheck } from "@phosphor-icons/react";
import { useEffect, useState } from "react";
import { platformApi } from "../../api";
import { usePlatformAuth } from "../../platformAuth";
import { Spinner } from "../../components/ui";
import {
  EmptyState,
  ErrorInline,
  PageHeader,
  PermissionMatrix,
  RoleBadge,
  SkeletonBlock,
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
    <section>
      <h3 className="mb-2 text-sm font-semibold text-text">MFA (TOTP)</h3>
      <div className="panel p-5">
        <p className="mb-3 text-[13px] text-muted">
          Protege tu cuenta de plataforma con un autenticador. Las operaciones críticas
          (impersonar, suspender, cancelar, resetear uso, routing de modelos) requieren MFA
          reciente.
        </p>
        {msg && <SuccessInline>{msg}</SuccessInline>}
        {error && <ErrorInline>{error}</ErrorInline>}
        {status?.enabled ? (
          <span className="badge badge-ok">Habilitado</span>
        ) : status?.pending ? (
          <span className="badge badge-pending">Pendiente de confirmar</span>
        ) : (
          <span className="badge badge-muted">Deshabilitado</span>
        )}
        <div className="mt-4 flex flex-wrap gap-2">
          {!status?.enabled && (
            <button type="button" className="btn btn-secondary min-h-10" disabled={busy} onClick={() => void enroll()}>
              {busy ? <Spinner size={14} /> : "Configurar"}
            </button>
          )}
          {status?.enabled && (
            <button type="button" className="btn btn-ghost min-h-10 text-danger" disabled={busy} onClick={() => void disable()}>
              Deshabilitar
            </button>
          )}
        </div>
        {otpAuthUrl && (
          <div className="mt-4 rounded-md border border-border bg-soft p-3">
            <p className="mb-2 text-xs text-muted">
              Escanea el QR o agrega el secreto manualmente en tu autenticador:
            </p>
            <p className="break-all font-mono text-xs text-accent">{secret}</p>
            <div className="mt-3 flex flex-wrap items-end gap-2">
              <label className="block text-xs text-muted">
                Código de confirmación
                <input
                  type="text"
                  inputMode="numeric"
                  value={code}
                  onChange={(e) => setCode(e.target.value.replace(/[^0-9]/g, ""))}
                  className="mt-1 w-40 rounded-md border border-border bg-bg px-3 py-2 font-mono text-sm"
                  placeholder="123456"
                />
              </label>
              <button type="button" className="btn btn-primary min-h-10" disabled={busy || !code.trim()} onClick={() => void verify()}>
                Confirmar
              </button>
            </div>
          </div>
        )}
      </div>
    </section>
  );
}

function SuccessInline({ children }: { children: string }) {
  if (!children) return null;
  return (
    <div className="mb-3 rounded-md border border-ok/25 bg-ok-soft px-3 py-2 text-sm text-ok" role="status">
      {children}
    </div>
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
    <div className="space-y-6">
      <PageHeader
        title="Security"
        subtitle="Usuarios de plataforma, roles granulares y matriz de permisos."
      />
      {error && <ErrorInline>{error}</ErrorInline>}
      {loading ? (
        <SkeletonBlock className="h-40" />
      ) : (
        <>
          <MfaPanel />
          <section>
            <h3 className="mb-2 text-sm font-semibold text-text">Usuarios de plataforma</h3>
            <div className="panel overflow-x-auto">
              {users.length === 0 ? (
                <EmptyState icon={ShieldCheck} title="Sin usuarios" body="No hay usuarios de plataforma." />
              ) : (
                <table className="table">
                  <thead>
                    <tr>
                      <th>Email</th>
                      <th>Roles</th>
                      <th>Legacy admin</th>
                    </tr>
                  </thead>
                  <tbody>
                    {users.map((u) => (
                      <tr key={u.id}>
                        <td className="text-sm">{u.email || u.id}</td>
                        <td>
                          <span className="inline-flex flex-wrap gap-1">
                            {u.roles.length === 0 && <span className="text-xs text-faint">sin rol</span>}
                            {u.roles.map((r) => (
                              <RoleBadge key={r} role={r} />
                            ))}
                          </span>
                        </td>
                        <td className="text-sm text-muted">{u.is_platform_admin ? "sí" : "no"}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
            </div>
          </section>
          <section>
            <h3 className="mb-2 text-sm font-semibold text-text">Matriz de permisos por rol</h3>
            <div className="panel">
              <PermissionMatrix roles={roles} />
            </div>
          </section>
        </>
      )}
    </div>
  );
}