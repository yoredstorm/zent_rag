import { Buildings } from "@phosphor-icons/react";
import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { platformApi } from "../../api";
import { EmptyState, ErrorInline, PageHeader, SkeletonBlock } from "../../components/ui";
import { usePlatformAuth } from "../../platformAuth";

type Org = {
  id: string;
  name: string;
  company_name: string | null;
  email: string | null;
  status: string;
};

export default function AdminCustomersPage() {
  const { session } = usePlatformAuth();
  const [orgs, setOrgs] = useState<Org[]>([]);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    if (!session) return;
    (async () => {
      setLoading(true);
      try {
        const data = await platformApi<{ organizations: Org[] }>(
          "/api/v1/platform/organizations",
          { token: session.token }
        );
        setOrgs(data.organizations || []);
        setError("");
      } catch (err) {
        setError(err instanceof Error ? err.message : "Error cargando clientes");
      } finally {
        setLoading(false);
      }
    })();
  }, [session]);

  return (
    <div>
      <PageHeader title="Clientes" subtitle="Organizaciones de la plataforma." />
      <ErrorInline message={error} />
      {loading && <SkeletonBlock />}
      {!loading && orgs.length === 0 && (
        <EmptyState icon={Buildings} title="Sin organizaciones" />
      )}
      {orgs.length > 0 && (
        <div className="panel overflow-x-auto">
          <table className="w-full min-w-[640px] text-left text-sm">
            <thead className="text-xs uppercase tracking-wide text-faint">
              <tr>
                <th className="px-4 py-3">Empresa</th>
                <th className="px-4 py-3">Email</th>
                <th className="px-4 py-3">Estado</th>
              </tr>
            </thead>
            <tbody>
              {orgs.map((o) => (
                <tr key={o.id} className="border-t border-border">
                  <td className="px-4 py-3">
                    <Link className="text-accent hover:underline" to={`/admin/customers/${o.id}`}>
                      {o.company_name || o.name}
                    </Link>
                  </td>
                  <td className="px-4 py-3 text-muted">{o.email || "—"}</td>
                  <td className="px-4 py-3">{o.status}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
