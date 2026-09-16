import {
  EnvelopeSimple,
  ShieldCheck,
  Trash,
  UserPlus,
  UsersThree,
  type Icon,
} from "@phosphor-icons/react";
import { useEffect, useState } from "react";
import { api } from "../api";
import { useAuth } from "../auth";
import {
  Badge,
  Button,
  CodeBlock,
  ConfirmDialog,
  DataTable,
  EmptyState,
  ErrorInline,
  Field,
  IconButton,
  Input,
  PageHeader,
  Panel,
  PanelHeader,
  RoleBadge,
  Select,
  SkeletonBlock,
  StatusBadge,
  SuccessInline,
  Tabs,
  TabsContent,
  TabsList,
  TabsTrigger,
  WarningInline,
  type Column,
} from "../components/ui";
import { fmtDateTime } from "../lib/format";

type Member = {
  user_id: string;
  email: string | null;
  external_id: string;
  role: string;
  is_system_role: boolean;
};

type Invite = {
  id: string;
  email: string;
  role: string;
  status: string;
  expires_at: string;
  created_at: string;
};

const INVITE_STATUS_LABELS: Record<string, string> = {
  pending: "Pendiente",
  accepted: "Aceptada",
  expired: "Vencida",
};

const ROLES = ["viewer", "member", "admin", "owner"];

const ROLE_INFO: Record<string, string> = {
  owner: "Control total del workspace, facturación y seguridad.",
  admin: "Gestión de miembros, claves y configuración.",
  member: "Uso de recursos, agentes y conocimiento.",
  viewer: "Solo lectura de dashboards y conocimiento.",
};

const TABS = [
  { id: "members", label: "Miembros", icon: UsersThree as Icon | undefined },
  { id: "invites", label: "Invitaciones", icon: UserPlus as Icon | undefined },
  { id: "roles", label: "Roles", icon: undefined },
  { id: "groups", label: "Grupos", icon: undefined },
] as const;

type TabId = (typeof TABS)[number]["id"];

export default function TeamAccessPage() {
  const { session } = useAuth();
  const [tab, setTab] = useState<TabId>("members");
  const [members, setMembers] = useState<Member[]>([]);
  const [invites, setInvites] = useState<Invite[]>([]);
  const [loading, setLoading] = useState(true);
  const [invitesLoading, setInvitesLoading] = useState(true);
  const [error, setError] = useState("");
  const [msg, setMsg] = useState("");
  const [pending, setPending] = useState<string | null>(null);
  const [removing, setRemoving] = useState<Member | null>(null);
  const [busyRemoving, setBusyRemoving] = useState(false);
  const [inviteEmail, setInviteEmail] = useState("");
  const [inviteRole, setInviteRole] = useState("member");
  const [inviting, setInviting] = useState(false);
  const [inviteToken, setInviteToken] = useState("");

  function load() {
    if (!session) return;
    setLoading(true);
    api<{ members: Member[] }>("/api/v1/organizations/members", {
      token: session.token,
      organizationId: session.organizationId,
    })
      .then((data) => setMembers(data.members || []))
      .catch((err) => setError(err instanceof Error ? err.message : "Error"))
      .finally(() => setLoading(false));
  }

  async function loadInvites() {
    if (!session) return;
    setInvitesLoading(true);
    try {
      const data = await api<{ invites: Invite[] }>("/api/v1/organizations/invites", {
        token: session.token,
        organizationId: session.organizationId,
      });
      setInvites(data.invites || []);
    } catch {
      // La lectura de invitaciones requiere `users:read`: si falla, los
      // miembros ya reportan el error del mismo permiso en su propia carga.
    } finally {
      setInvitesLoading(false);
    }
  }

  useEffect(() => {
    load();
    void loadInvites();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [session]);

  async function changeRole(userId: string, role: string) {
    if (!session) return;
    setError("");
    setMsg("");
    setPending(userId);
    try {
      await api(`/api/v1/organizations/members/${userId}/role`, {
        method: "POST",
        token: session.token,
        organizationId: session.organizationId,
        body: JSON.stringify({ role }),
      });
      setMsg(`Rol actualizado a "${role}".`);
      load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Error al cambiar rol");
      load();
    } finally {
      setPending(null);
    }
  }

  async function invite() {
    if (!session || !inviteEmail.trim()) return;
    setError("");
    setMsg("");
    setInviteToken("");
    setInviting(true);
    try {
      const created = await api<{ token: string }>("/api/v1/organizations/invites", {
        method: "POST",
        token: session.token,
        organizationId: session.organizationId,
        body: JSON.stringify({ email: inviteEmail.trim(), role: inviteRole }),
      });
      setInviteToken(created.token);
      setMsg("Invitación creada. Copiá el enlace/token ahora; no se volverá a mostrar.");
      setInviteEmail("");
      void loadInvites();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Error al invitar");
    } finally {
      setInviting(false);
    }
  }

  async function removeMember() {
    if (!session || !removing) return;
    setError("");
    setMsg("");
    setBusyRemoving(true);
    try {
      await api(`/api/v1/organizations/members/${removing.user_id}`, {
        method: "DELETE",
        token: session.token,
        organizationId: session.organizationId,
      });
      setMsg("Miembro removido.");
      setRemoving(null);
      load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Error al remover");
    } finally {
      setBusyRemoving(false);
    }
  }

  const columns: Column<Member>[] = [
    {
      key: "member",
      header: "Miembro",
      render: (m) => (
        <div className="min-w-0">
          <p className="truncate text-[13.5px] text-text">{m.email || "—"}</p>
          <p className="mono mt-0.5 truncate text-[11px] text-faint">{m.external_id}</p>
        </div>
      ),
    },
    {
      key: "role",
      header: "Rol",
      render: (m) => (
        <span className="flex flex-wrap items-center gap-1.5">
          <RoleBadge role={m.role} />
          {m.is_system_role && <Badge tone="neutral">Sistema</Badge>}
        </span>
      ),
    },
    {
      key: "actions",
      header: "Acciones",
      align: "right",
      render: (m) => (
        <span className="flex flex-wrap items-center justify-end gap-1.5">
          <Select
            className="min-h-9 w-auto text-[13px]"
            value={m.role}
            disabled={pending === m.user_id}
            aria-label={`Rol de ${m.email || m.external_id}`}
            onChange={(e) => void changeRole(m.user_id, e.target.value)}
          >
            {ROLES.map((r) => (
              <option key={r} value={r}>
                {roleLabel(r)}
              </option>
            ))}
          </Select>
          <IconButton
            label={`Remover ${m.email || m.external_id}`}
            icon={Trash}
            className="text-danger"
            disabled={pending === m.user_id}
            onClick={() => setRemoving(m)}
          />
        </span>
      ),
    },
  ];

  const inviteColumns: Column<Invite>[] = [
    {
      key: "email",
      header: "Email",
      render: (inv) => <span className="truncate text-[13.5px] text-text">{inv.email}</span>,
    },
    {
      key: "role",
      header: "Rol",
      render: (inv) => <RoleBadge role={inv.role} />,
    },
    {
      key: "status",
      header: "Estado",
      render: (inv) => (
        <StatusBadge status={inv.status} label={INVITE_STATUS_LABELS[inv.status]} />
      ),
    },
    {
      key: "expires_at",
      header: "Expira",
      hideBelow: "md",
      render: (inv) => <span className="text-xs text-muted">{fmtDateTime(inv.expires_at)}</span>,
    },
    {
      key: "created_at",
      header: "Creada",
      hideBelow: "lg",
      render: (inv) => <span className="text-xs text-muted">{fmtDateTime(inv.created_at)}</span>,
    },
  ];

  return (
    <div>
      <PageHeader
        title="Equipo y Acceso"
        subtitle="Administra quién puede acceder a tu workspace, sus roles y las invitaciones pendientes."
      />
      <Tabs value={tab} onValueChange={(value) => setTab(value as TabId)}>
        <TabsList>
          {TABS.map(({ id, label, icon }) => (
            <TabsTrigger key={id} value={id} icon={icon}>
              {label}
            </TabsTrigger>
          ))}
        </TabsList>

        <TabsContent value="members">
          <ErrorInline message={error} />
          <SuccessInline message={msg} />
          {loading ? (
            <Panel>
              <div className="panel-body">
                <SkeletonBlock rows={4} />
              </div>
            </Panel>
          ) : (
            <DataTable
              columns={columns}
              rows={members}
              rowKey={(m) => m.user_id}
              caption="Miembros de la organización"
              empty={
                <EmptyState
                  icon={UserPlus}
                  title="Sin miembros"
                  body="Invitá a tu equipo para colaborar en este workspace."
                  action={
                    <Button
                      variant="primary"
                      leadingIcon={UserPlus}
                      onClick={() => setTab("invites")}
                    >
                      Invitar usuario
                    </Button>
                  }
                />
              }
              footer={
                members.length > 0 ? (
                  <p className="text-xs text-muted tabular-nums">
                    {members.length} {members.length === 1 ? "miembro" : "miembros"}
                  </p>
                ) : undefined
              }
            />
          )}
        </TabsContent>

        <TabsContent value="invites" className="space-y-4">
          <ErrorInline message={error} />
          <SuccessInline message={msg} />
          <Panel>
            <PanelHeader
              title="Invitar usuario"
              description="Se crea un token de un solo uso para que la persona se una con el rol elegido."
            />
            <form
              className="panel-body"
              onSubmit={(e) => {
                e.preventDefault();
                void invite();
              }}
            >
              <div className="grid gap-4 sm:grid-cols-[minmax(0,1fr)_200px_auto] sm:items-end">
                <Field label="Email">
                  <Input
                    type="email"
                    required
                    autoComplete="email"
                    value={inviteEmail}
                    onChange={(e) => setInviteEmail(e.target.value)}
                  />
                </Field>
                <Field label="Rol">
                  <Select value={inviteRole} onChange={(e) => setInviteRole(e.target.value)}>
                    {ROLES.map((r) => (
                      <option key={r} value={r}>
                        {roleLabel(r)}
                      </option>
                    ))}
                  </Select>
                </Field>
                <Button type="submit" variant="primary" loading={inviting} leadingIcon={UserPlus}>
                  Enviar invitación
                </Button>
              </div>
              {inviteToken && (
                <div className="mt-4">
                  <WarningInline className="mb-3">
                    Este token se muestra una sola vez. Copialo y compartilo por un canal seguro.
                  </WarningInline>
                  <CodeBlock
                    code={inviteToken}
                    language="text"
                    filename="Token de invitación (una vez)"
                    maxHeight={140}
                  />
                </div>
              )}
            </form>
          </Panel>

          <Panel>
            <PanelHeader
              title="Invitaciones"
              description="Tokens emitidos por la organización y su estado actual."
            />
            <DataTable
              columns={inviteColumns}
              rows={invites}
              rowKey={(inv) => inv.id}
              caption="Invitaciones de la organización"
              loading={invitesLoading}
              empty={
                <EmptyState
                  icon={EnvelopeSimple}
                  title="Sin invitaciones"
                  body="Cuando invites a alguien, su token y vencimiento aparecen acá."
                />
              }
            />
          </Panel>
        </TabsContent>

        <TabsContent value="roles">
          <Panel>
            <PanelHeader
              title="Roles del workspace"
              description="El rol define qué puede ver y hacer cada miembro."
            />
            <div className="divide-y divide-border-soft">
              {ROLES.map((role) => (
                <div key={role} className="flex items-center justify-between gap-3 px-4 py-3">
                  <div className="min-w-0">
                    <p className="text-[13.5px] font-medium text-text">{roleLabel(role)}</p>
                    <p className="mt-0.5 text-xs text-muted">{ROLE_INFO[role]}</p>
                  </div>
                  <RoleBadge role={role} />
                </div>
              ))}
            </div>
            <p className="flex items-center gap-2 border-t border-border px-4 py-3 text-xs text-faint">
              <ShieldCheck size={14} className="text-accent" aria-hidden />
              Los permisos se evalúan en el servidor en cada operación.
            </p>
          </Panel>
        </TabsContent>

        <TabsContent value="groups">
          <Panel>
            <EmptyState
              icon={UsersThree}
              title="Grupos de acceso"
              body="Los grupos te permitirán agrupar miembros y otorgar permisos por conjunto de recursos."
              hint="Disponible en una próxima fase."
            />
          </Panel>
        </TabsContent>
      </Tabs>

      <ConfirmDialog
        open={removing !== null}
        onOpenChange={(open) => {
          if (!open) setRemoving(null);
        }}
        title="Remover miembro"
        body={
          removing
            ? `Se quita el acceso de ${removing.email || removing.external_id} a esta organización. Podés volver a invitarlo cuando quieras.`
            : undefined
        }
        confirmLabel="Remover"
        loading={busyRemoving}
        onConfirm={() => void removeMember()}
      />
    </div>
  );
}

function roleLabel(role: string): string {
  const labels: Record<string, string> = {
    viewer: "Lectura",
    member: "Miembro",
    admin: "Admin",
    owner: "Owner",
  };
  return labels[role] ?? role;
}
