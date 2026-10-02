import {
  CheckCircle,
  Clock,
  DotsThreeVertical,
  Envelope,
  Key,
  Plus,
  Question,
  ShieldCheck,
  UserMinus,
  UserPlus,
  WarningOctagon,
} from "@phosphor-icons/react";
import { useEffect, useState } from "react";
import { platformApi } from "../../api";
import { usePlatformAuth } from "../../platformAuth";
import { ConfirmDialog } from "../../components/ConfirmDialog";
import {
  Badge,
  Button,
  CodeBlock,
  DataTable,
  EmptyState,
  ErrorInline,
  Field,
  Input,
  Menu,
  MenuItem,
  PageHeader,
  Panel,
  PanelHeader,
  PermissionMatrix,
  ResultCount,
  RoleBadge,
  Select,
  SkeletonBlock,
  SuccessInline,
  type Column,
} from "../../components/ui";

type PlatformUser = {
  id: string;
  email: string | null;
  is_platform_admin: boolean;
  roles: string[];
  disabled_at?: string | null;
};

type PlatformRole = {
  id: string;
  name: string;
  description: string | null;
  is_system: boolean;
  permissions: string[];
};

const menuItemClass =
  "flex items-center gap-2 rounded-sm px-2.5 py-1.5 text-[13px] text-text hover:bg-soft focus:bg-soft outline-none";

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
            <Button
              variant="ghost"
              className="text-danger"
              disabled={busy}
              onClick={() => void disable()}
            >
              Deshabilitar
            </Button>
          )}
        </div>
        {otpAuthUrl && (
          <div className="rounded-md border border-border bg-raised p-3">
            <p className="mb-2 text-xs leading-relaxed text-muted">
              Escanea el QR o agrega el secreto manualmente en tu autenticador:
            </p>
            <p className="mono rounded-sm bg-control px-2.5 py-1.5 text-xs break-all text-accent">
              {secret}
            </p>
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
  const [notice, setNotice] = useState("");
  const [busy, setBusy] = useState("");

  // Crear
  const [createEmail, setCreateEmail] = useState("");
  const [createRole, setCreateRole] = useState("");
  const [createdToken, setCreatedToken] = useState<{ email: string; token: string } | null>(null);

  // Diálogos
  const [confirmAction, setConfirmAction] = useState<
    | { kind: "deactivate"; user: PlatformUser }
    | { kind: "activate"; user: PlatformUser }
    | { kind: "password-reset"; user: PlatformUser }
    | { kind: "revoke-role"; user: PlatformUser; role: string }
    | null
  >(null);
  const [assignTarget, setAssignTarget] = useState<PlatformUser | null>(null);
  const [assignRole, setAssignRole] = useState("");
  const [emailTarget, setEmailTarget] = useState<PlatformUser | null>(null);
  const [emailValue, setEmailValue] = useState("");

  async function load() {
    if (!session) return;
    try {
      const [u, r] = await Promise.all([
        platformApi<{ users: PlatformUser[] }>("/api/v1/platform/users", { token: session.token }),
        platformApi<{ roles: PlatformRole[] }>("/api/v1/platform/roles", { token: session.token }),
      ]);
      setUsers(u.users || []);
      setRoles(r.roles || []);
      setError("");
    } catch (e) {
      setError(e instanceof Error ? e.message : "Error");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    void load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [session]);

  async function create() {
    if (!session) return;
    setBusy("create");
    setError("");
    setNotice("");
    setCreatedToken(null);
    try {
      const out = await platformApi<{ user_id: string; email: string; reset_token: string }>(
        "/api/v1/platform/users",
        {
          method: "POST",
          token: session.token,
          body: JSON.stringify({ email: createEmail, role_name: createRole }),
        }
      );
      setCreatedToken({ email: out.email, token: out.reset_token });
      setNotice(`Usuario creado: ${out.email}. Copia el token; no se vuelve a mostrar.`);
      setCreateEmail("");
      setCreateRole("");
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : "No se pudo crear el usuario");
    } finally {
      setBusy("");
    }
  }

  async function runAction() {
    if (!session || !confirmAction) return;
    setBusy(confirmAction.kind);
    setError("");
    setNotice("");
    try {
      if (confirmAction.kind === "deactivate") {
        await platformApi(`/api/v1/platform/users/${confirmAction.user.id}/deactivate`, {
          method: "POST",
          token: session.token,
          body: "{}",
        });
        setNotice(`${confirmAction.user.email} desactivado.`);
      } else if (confirmAction.kind === "activate") {
        await platformApi(`/api/v1/platform/users/${confirmAction.user.id}/activate`, {
          method: "POST",
          token: session.token,
          body: "{}",
        });
        setNotice(`${confirmAction.user.email} reactivado.`);
      } else if (confirmAction.kind === "password-reset") {
        const out = await platformApi<{ reset_token: string }>(
          `/api/v1/platform/users/${confirmAction.user.id}/password-reset`,
          { method: "POST", token: session.token, body: "{}" }
        );
        setCreatedToken({ email: confirmAction.user.email || "", token: out.reset_token });
        setNotice("Token de reset generado. Cópialo ahora; no se volverá a mostrar.");
      } else if (confirmAction.kind === "revoke-role") {
        await platformApi(`/api/v1/platform/users/${confirmAction.user.id}/roles`, {
          method: "POST",
          token: session.token,
          body: JSON.stringify({ role_name: confirmAction.role, action: "revoke" }),
        });
        setNotice(`Rol ${confirmAction.role} revocado de ${confirmAction.user.email}.`);
      }
      setConfirmAction(null);
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : "La acción falló");
    } finally {
      setBusy("");
    }
  }

  async function runAssign() {
    if (!session || !assignTarget || !assignRole) return;
    setBusy("assign-role");
    setError("");
    setNotice("");
    try {
      await platformApi(`/api/v1/platform/users/${assignTarget.id}/roles`, {
        method: "POST",
        token: session.token,
        body: JSON.stringify({ role_name: assignRole, action: "assign" }),
      });
      setNotice(`Rol ${assignRole} asignado a ${assignTarget.email}.`);
      setAssignTarget(null);
      setAssignRole("");
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : "No se pudo asignar el rol");
    } finally {
      setBusy("");
    }
  }

  async function runEmailUpdate() {
    if (!session || !emailTarget || !emailValue.trim()) return;
    setBusy("update-email");
    setError("");
    setNotice("");
    try {
      await platformApi(`/api/v1/platform/users/${emailTarget.id}`, {
        method: "PATCH",
        token: session.token,
        body: JSON.stringify({ email: emailValue.trim() }),
      });
      setNotice(`Email actualizado a ${emailValue.trim()}.`);
      setEmailTarget(null);
      setEmailValue("");
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : "No se pudo actualizar el email");
    } finally {
      setBusy("");
    }
  }

  const selfEmail = session?.email || "";

  const userColumns: Column<PlatformUser>[] = [
    {
      key: "email",
      header: "Email",
      render: (u) => (
        <span className="text-[13px] text-text">
          {u.email || u.id}
          {u.email === selfEmail && (
            <span className="ml-2 text-[11px] text-muted">(tú)</span>
          )}
        </span>
      ),
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
      key: "state",
      header: "Estado",
      render: (u) =>
        u.disabled_at ? (
          <Badge tone="danger" icon={WarningOctagon}>
            Suspendido
          </Badge>
        ) : (
          <Badge tone="ok" icon={CheckCircle}>
            Activo
          </Badge>
        ),
    },
    {
      key: "legacy",
      header: "Legacy",
      hideBelow: "lg",
      render: (u) =>
        u.is_platform_admin ? (
          <Badge tone="neutral">sí</Badge>
        ) : (
          <Badge tone="neutral">no</Badge>
        ),
    },
  ];

  const isSelf = (u: PlatformUser) => u.email === selfEmail;
  const availableRoles = roles.filter((r) => !r.is_system || r.name !== "super_admin");

  return (
    <div className="space-y-4">
      <PageHeader
        title="Security"
        subtitle="Usuarios de plataforma, roles granulares y matriz de permisos."
      />
      {error && <ErrorInline>{error}</ErrorInline>}
      {notice && <SuccessInline message={notice} />}
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
                  Cuentas con acceso al Control Center. Control total: crear, desactivar, roles, email y reset.
                </p>
              </div>
            </div>
            <DataTable
              columns={userColumns}
              rows={users}
              rowKey={(u) => u.id}
              caption="Usuarios de plataforma"
              stickyHeader
              rowActions={(u) => (
                <Menu
                  label={`Acciones para ${u.email || u.id}`}
                  trigger={
                    <Button variant="ghost" size="sm" leadingIcon={DotsThreeVertical} aria-label="Acciones" />
                  }
                >
                  <MenuItem
                    className={menuItemClass}
                    onSelect={() => {
                      setAssignTarget(u);
                      setAssignRole("");
                    }}
                  >
                    <UserPlus size={14} aria-hidden />
                    Asignar rol…
                  </MenuItem>
                  {u.roles.length > 0 && (
                    <MenuItem
                      className={menuItemClass}
                      onSelect={() => {
                        setAssignTarget(u);
                        setAssignRole("");
                      }}
                    >
                      <UserMinus size={14} aria-hidden />
                      Revocar rol…
                    </MenuItem>
                  )}
                  <MenuItem
                    className={menuItemClass}
                    onSelect={() => {
                      setEmailTarget(u);
                      setEmailValue(u.email || "");
                    }}
                  >
                    <Envelope size={14} aria-hidden />
                    Editar email…
                  </MenuItem>
                  <MenuItem
                    className={menuItemClass}
                    onSelect={() => setConfirmAction({ kind: "password-reset", user: u })}
                  >
                    <Key size={14} aria-hidden />
                    Reset de contraseña
                  </MenuItem>
                  {u.disabled_at ? (
                    <MenuItem
                      className={menuItemClass}
                      onSelect={() => setConfirmAction({ kind: "activate", user: u })}
                    >
                      <UserPlus size={14} aria-hidden />
                      Reactivar
                    </MenuItem>
                  ) : (
                    <MenuItem
                      className={menuItemClass}
                      disabled={isSelf(u)}
                      onSelect={() => setConfirmAction({ kind: "deactivate", user: u })}
                    >
                      <UserMinus size={14} aria-hidden />
                      Desactivar
                    </MenuItem>
                  )}
                </Menu>
              )}
              empty={
                <EmptyState
                  icon={ShieldCheck}
                  title="Sin usuarios"
                  body="No hay usuarios de plataforma registrados."
                />
              }
              footer={
                users.length > 0 ? (
                  <ResultCount shown={users.length} total={users.length} noun="usuarios" />
                ) : undefined
              }
            />
          </section>

          <section>
            <div className="mb-3">
              <h2 className="text-h2">Nuevo usuario de plataforma</h2>
              <p className="mt-1 text-[13px] leading-relaxed text-muted">
                Se genera un usuario sin contraseña: recibe un token de reset (una sola vez) para definir la suya.
              </p>
            </div>
            <Panel>
              <form
                className="grid grid-cols-1 gap-3 p-4 lg:grid-cols-4 lg:items-end"
                onSubmit={(e) => {
                  e.preventDefault();
                  void create();
                }}
              >
                <Field label="Email">
                  <Input
                    type="email"
                    value={createEmail}
                    onChange={(e) => setCreateEmail(e.target.value)}
                    placeholder="usuario@zent.dev"
                    required
                  />
                </Field>
                <Field label="Rol inicial">
                  <Select
                    value={createRole}
                    onChange={(e) => setCreateRole(e.target.value)}
                    placeholder="Seleccionar…"
                    required
                  >
                    <option value="" disabled>
                      Seleccionar rol
                    </option>
                    {roles.map((r) => (
                      <option key={r.id} value={r.name}>
                        {r.name}
                      </option>
                    ))}
                  </Select>
                </Field>
                <Button type="submit" variant="primary" loading={busy === "create"} leadingIcon={Plus}>
                  Crear usuario
                </Button>
              </form>
              {createdToken && (
                <div className="border-t border-border-soft p-4">
                  <SuccessInline
                    message={`Usuario ${createdToken.email} listo. Token de reset (una sola vez):`}
                  />
                  <div className="mt-2">
                    <CodeBlock filename="reset-token" code={createdToken.token} />
                  </div>
                </div>
              )}
            </Panel>
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

      {/* Asignar/Revocar rol */}
      <ConfirmDialog
        open={!!assignTarget}
        title={
          assignTarget
            ? assignTarget.roles.includes(assignRole)
              ? `Revocar rol ${assignRole} de ${assignTarget.email}?`
              : `Asignar rol a ${assignTarget.email}`
            : ""
        }
        body={
          <div className="flex flex-col gap-3">
            <Select
              value={assignRole}
              onChange={(e) => setAssignRole(e.target.value)}
              placeholder="Seleccionar rol"
            >
              <option value="" disabled>
                Seleccionar rol
              </option>
              {availableRoles.map((r) => (
                <option key={r.id} value={r.name}>
                  {r.name}
                  {assignTarget?.roles.includes(r.name) ? " (ya asignado)" : ""}
                </option>
              ))}
            </Select>
          </div>
        }
        confirmLabel={
          assignTarget && assignTarget.roles.includes(assignRole) ? "Revocar" : "Asignar"
        }
        tone={assignTarget && assignTarget.roles.includes(assignRole) ? "danger" : "default"}
        busy={busy === "assign-role"}
        onConfirm={() => {
          if (!assignTarget || !assignRole) return;
          if (assignTarget.roles.includes(assignRole)) {
            setConfirmAction({ kind: "revoke-role", user: assignTarget, role: assignRole });
            setAssignTarget(null);
            setTimeout(() => void runAction(), 0);
          } else {
            void runAssign();
          }
        }}
        onCancel={() => setAssignTarget(null)}
      />

      {/* Editar email */}
      <ConfirmDialog
        open={!!emailTarget}
        title={`Editar email de ${emailTarget?.email || ""}`}
        body={
          <Field label="Nuevo email">
            <Input
              type="email"
              value={emailValue}
              onChange={(e) => setEmailValue(e.target.value)}
              placeholder="nuevo@email.com"
            />
          </Field>
        }
        confirmLabel="Guardar"
        tone="default"
        busy={busy === "update-email"}
        onConfirm={() => void runEmailUpdate()}
        onCancel={() => setEmailTarget(null)}
      />

      {/* Confirmaciones (desactivar / reactivar / reset / revocar rol) */}
      <ConfirmDialog
        open={!!confirmAction}
        title={
          confirmAction?.kind === "deactivate"
            ? `Desactivar a ${confirmAction.user.email}?`
            : confirmAction?.kind === "activate"
              ? `Reactivar a ${confirmAction.user.email}?`
              : confirmAction?.kind === "password-reset"
                ? `Reset de contraseña para ${confirmAction.user.email}?`
                : confirmAction?.kind === "revoke-role"
                  ? `Revocar ${confirmAction.role} de ${confirmAction.user.email}?`
                  : ""
        }
        body={
          confirmAction?.kind === "deactivate"
            ? "El usuario quedará suspendido: sus sesiones se cierran al instante y no podrá iniciar sesión hasta reactivarlo."
            : confirmAction?.kind === "activate"
              ? "Se restablece el acceso. El usuario deberá iniciar sesión de nuevo."
              : confirmAction?.kind === "password-reset"
                ? "Se generará un token de reset válido por 1 hora. Todas sus sesiones se cerrarán al aplicar el cambio."
                : "Se aplicará el cambio de rol de inmediato."
        }
        confirmLabel={
          confirmAction?.kind === "deactivate"
            ? "Desactivar"
            : confirmAction?.kind === "activate"
              ? "Reactivar"
              : confirmAction?.kind === "password-reset"
                ? "Generar token"
                : "Revocar"
        }
        tone={
          confirmAction?.kind === "deactivate" || confirmAction?.kind === "revoke-role"
            ? "danger"
            : "default"
        }
        busy={busy === "deactivate" || busy === "activate" || busy === "password-reset"}
        onConfirm={() => void runAction()}
        onCancel={() => setConfirmAction(null)}
      />
    </div>
  );
}
