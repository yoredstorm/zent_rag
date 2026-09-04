import { ShieldCheck, UserPlus, UsersThree } from "@phosphor-icons/react";
import { useEffect, useState } from "react";
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
  SuccessInline,
} from "../components/ui";

type Member = {
  user_id: string;
  email: string | null;
  external_id: string;
  role: string;
  is_system_role: boolean;
};

const ROLES = ["viewer", "member", "admin", "owner"];

const ROLE_INFO: Record<string, string> = {
  owner: "Control total del workspace, facturación y seguridad.",
  admin: "Gestión de miembros, claves y configuración.",
  member: "Uso de recursos, agentes y conocimiento.",
  viewer: "Solo lectura de dashboards y conocimiento.",
};

const TABS = [
  { id: "members", label: "Miembros", icon: UsersThree },
  { id: "invites", label: "Invitaciones", icon: UserPlus },
  { id: "roles", label: "Roles" },
  { id: "groups", label: "Grupos" },
] as const;

type TabId = (typeof TABS)[number]["id"];

export default function TeamAccessPage() {
  const { session } = useAuth();
  const [tab, setTab] = useState<TabId>("members");
  const [members, setMembers] = useState<Member[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [msg, setMsg] = useState("");
  const [pending, setPending] = useState<string | null>(null);
  const [removing, setRemoving] = useState<string | null>(null);
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
      .then((data) => setMembers(data.members))
      .catch((err) => setError(err instanceof Error ? err.message : "Error"))
      .finally(() => setLoading(false));
  }

  useEffect(load, [session]);

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
      setMsg("Invitación creada. Copia el enlace/token ahora; no se volverá a mostrar.");
      setInviteEmail("");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Error al invitar");
    } finally {
      setInviting(false);
    }
  }

  async function removeMember(userId: string) {
    if (!session) return;
    setError("");
    setMsg("");
    setRemoving(userId);
    try {
      await api(`/api/v1/organizations/members/${userId}`, {
        method: "DELETE",
        token: session.token,
        organizationId: session.organizationId,
      });
      setMsg("Miembro removido.");
      load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Error al remover");
    } finally {
      setRemoving(null);
    }
  }

  return (
    <div>
      <PageHeader
        title="Equipo y Acceso"
        subtitle="Administra quién puede acceder a tu workspace, sus roles y las invitaciones pendientes."
      />
      <PageTabs
        tabs={TABS}
        active={tab}
        onChange={(id) => setTab(id as TabId)}
        idPrefix="team"
      />
      <ErrorInline message={error} />
      <SuccessInline message={msg} />

      {tab === "members" && (
        <div className="panel mt-4">
          <div className="flex items-center justify-between border-b border-border px-5 py-4">
            <h2 className="flex items-center gap-2 text-sm font-semibold text-text">
              <UsersThree size={16} className="text-accent" aria-hidden />
              Miembros ({members.length})
            </h2>
          </div>
          {loading ? (
            <div className="p-5">
              <SkeletonBlock rows={4} />
            </div>
          ) : members.length === 0 ? (
            <EmptyState
              icon={UserPlus}
              title="Sin miembros"
              body="Invita a tu equipo para colaborar en este workspace."
            />
          ) : (
            <div className="overflow-x-auto">
              <table className="table min-w-[560px]">
                <thead>
                  <tr>
                    <th>Email</th>
                    <th>ID externo</th>
                    <th>Rol</th>
                    <th className="text-right">Acciones</th>
                  </tr>
                </thead>
                <tbody>
                  {members.map((m) => (
                    <tr key={m.user_id}>
                      <td className="font-medium text-text">{m.email || "—"}</td>
                      <td className="mono text-xs">{m.external_id}</td>
                      <td>
                        <span className="badge badge-ok">
                          <ShieldCheck size={13} aria-hidden /> {m.role}
                        </span>
                      </td>
                      <td className="text-right">
                        <div className="flex items-center justify-end gap-2">
                          <select
                            className="rounded-md border border-border bg-soft px-2 py-1.5 text-xs text-text outline-none focus:border-accent"
                            value={m.role}
                            disabled={pending === m.user_id}
                            onChange={(e) => void changeRole(m.user_id, e.target.value)}
                            aria-label={`Rol de ${m.email || m.external_id}`}
                          >
                            {ROLES.map((r) => (
                              <option key={r} value={r}>
                                {r}
                              </option>
                            ))}
                          </select>
                          <button
                            type="button"
                            className="btn btn-ghost px-2 py-1.5 text-xs text-danger"
                            disabled={removing === m.user_id}
                            onClick={() => void removeMember(m.user_id)}
                            aria-label={`Remover ${m.email || m.external_id}`}
                          >
                            {removing === m.user_id ? <Spinner size={13} /> : "Remover"}
                          </button>
                        </div>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      )}

      {tab === "invites" && (
        <form
          className="panel mt-4 p-5"
          onSubmit={(e) => {
            e.preventDefault();
            void invite();
          }}
        >
          <h2 className="mb-3 flex items-center gap-2 text-sm font-semibold text-text">
            <UserPlus size={16} className="text-accent" aria-hidden />
            Invitar usuario
          </h2>
          <div className="flex flex-col gap-3 sm:flex-row sm:items-end">
            <label className="block flex-1 text-sm">
              <span className="mb-1 block text-muted">Email</span>
              <input
                type="email"
                required
                autoComplete="email"
                className="w-full rounded-md border border-border bg-soft px-3 py-2.5 text-sm text-text outline-none focus:border-accent"
                value={inviteEmail}
                onChange={(e) => setInviteEmail(e.target.value)}
              />
            </label>
            <label className="block text-sm">
              <span className="mb-1 block text-muted">Rol</span>
              <select
                className="min-h-11 rounded-md border border-border bg-soft px-2 py-2.5 text-sm text-text outline-none focus:border-accent"
                value={inviteRole}
                onChange={(e) => setInviteRole(e.target.value)}
              >
                {ROLES.map((r) => (
                  <option key={r} value={r}>
                    {r}
                  </option>
                ))}
              </select>
            </label>
            <button type="submit" className="btn btn-primary min-h-11" disabled={inviting}>
              {inviting ? <Spinner size={14} /> : "Enviar invitación"}
            </button>
          </div>
          {inviteToken && (
            <p className="mt-3 break-all rounded-md border border-border bg-soft px-3 py-2 font-mono text-xs text-muted">
              Token (una vez): {inviteToken}
            </p>
          )}
        </form>
      )}

      {tab === "roles" && (
        <div className="panel mt-4">
          <div className="border-b border-border px-5 py-4">
            <h2 className="text-sm font-semibold text-text">Roles del workspace</h2>
          </div>
          <div className="divide-y divide-border/60">
            {ROLES.map((role) => (
              <div key={role} className="flex items-center justify-between gap-3 px-5 py-3">
                <div>
                  <p className="mono text-sm font-medium text-text">{role}</p>
                  <p className="text-[12px] text-muted">{ROLE_INFO[role]}</p>
                </div>
                <span className="badge badge-ok">{role}</span>
              </div>
            ))}
          </div>
        </div>
      )}

      {tab === "groups" && (
        <div className="mt-4">
          <ComingSoon>
            Los grupos de acceso te permitirán agrupar miembros y otorgar permisos por conjunto de
            recursos. Disponible en una próxima fase.
          </ComingSoon>
        </div>
      )}
    </div>
  );
}