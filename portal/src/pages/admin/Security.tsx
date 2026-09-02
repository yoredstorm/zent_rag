import { ShieldCheck } from "@phosphor-icons/react";
import { useEffect, useState } from "react";
import { platformApi } from "../../api";
import { usePlatformAuth } from "../../platformAuth";
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