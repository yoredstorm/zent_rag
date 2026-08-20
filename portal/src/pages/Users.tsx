import { ShieldCheck, UserPlus, UsersThree } from "@phosphor-icons/react";
import { useEffect, useState } from "react";
import { api } from "../api";
import { useAuth } from "../auth";
import { useToast } from "../Toast";
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

export default function UsersPage() {
  const { session } = useAuth();
  const { pushToast } = useToast();
  const [members, setMembers] = useState<Member[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [msg, setMsg] = useState("");
  const [pending, setPending] = useState<string | null>(null);
  const [removing, setRemoving] = useState<string | null>(null);

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
        title="Usuarios y roles"
        subtitle="Roles: owner (control total), admin (gestión), member (uso + recursos) y viewer (solo lectura)."
      />
      <ErrorInline message={error} />
      <SuccessInline message={msg} />

      <div className="panel">
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
            body="Tu organización no tiene miembros registrados."
          />
        ) : (
          <table className="table">
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
        )}
      </div>
    </div>
  );
}
