import { useEffect, useState } from "react";
import { api } from "../api";
import { useAuth } from "../auth";
import {
  ErrorInline,
  PageHeader,
  SkeletonBlock,
  Spinner,
  SuccessInline,
} from "../components/ui";

type OrgProfile = {
  name: string;
  company_name: string | null;
  country: string | null;
  email: string | null;
  phone: string | null;
};

export default function SettingsPage() {
  const { session } = useAuth();
  const [profile, setProfile] = useState<OrgProfile>({
    name: "",
    company_name: "",
    country: "",
    email: "",
    phone: "",
  });
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const [msg, setMsg] = useState("");

  useEffect(() => {
    if (!session) return;
    setLoading(true);
    api<OrgProfile>("/api/v1/organizations", {
      token: session.token,
      organizationId: session.organizationId,
    })
      .then((data) =>
        setProfile({
          name: data.name || "",
          company_name: data.company_name || "",
          country: data.country || "",
          email: data.email || "",
          phone: data.phone || "",
        })
      )
      .catch((err) => setError(err instanceof Error ? err.message : "Error"))
      .finally(() => setLoading(false));
  }, [session]);

  async function save() {
    if (!session) return;
    setSaving(true);
    setError("");
    setMsg("");
    try {
      await api("/api/v1/organizations", {
        method: "PUT",
        token: session.token,
        organizationId: session.organizationId,
        body: JSON.stringify({
          name: profile.name,
          company_name: profile.company_name,
          country: profile.country,
          email: profile.email,
          phone: profile.phone,
        }),
      });
      setMsg("Organización actualizada.");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Error al guardar");
    } finally {
      setSaving(false);
    }
  }

  return (
    <div>
      <PageHeader
        title="Ajustes"
        subtitle="Perfil de la organización. El restablecimiento de contraseña llega en una fase posterior."
      />
      <ErrorInline message={error} />
      <SuccessInline message={msg} />
      {loading ? (
        <div className="panel p-5">
          <SkeletonBlock rows={5} />
        </div>
      ) : (
        <form
          className="panel max-w-xl space-y-3 p-5"
          onSubmit={(e) => {
            e.preventDefault();
            void save();
          }}
        >
          <label className="block text-sm">
            <span className="mb-1 block text-muted">Nombre</span>
            <input
              className="w-full rounded-md border border-border bg-soft px-3 py-2.5 text-sm text-text outline-none focus:border-accent"
              value={profile.name}
              onChange={(e) => setProfile((p) => ({ ...p, name: e.target.value }))}
              autoComplete="organization"
            />
          </label>
          <label className="block text-sm">
            <span className="mb-1 block text-muted">Empresa</span>
            <input
              className="w-full rounded-md border border-border bg-soft px-3 py-2.5 text-sm text-text outline-none focus:border-accent"
              value={profile.company_name || ""}
              onChange={(e) =>
                setProfile((p) => ({ ...p, company_name: e.target.value }))
              }
              autoComplete="organization"
            />
          </label>
          <label className="block text-sm">
            <span className="mb-1 block text-muted">País</span>
            <input
              className="w-full rounded-md border border-border bg-soft px-3 py-2.5 text-sm text-text outline-none focus:border-accent"
              value={profile.country || ""}
              onChange={(e) => setProfile((p) => ({ ...p, country: e.target.value }))}
              autoComplete="country-name"
            />
          </label>
          <label className="block text-sm">
            <span className="mb-1 block text-muted">Email</span>
            <input
              type="email"
              className="w-full rounded-md border border-border bg-soft px-3 py-2.5 text-sm text-text outline-none focus:border-accent"
              value={profile.email || ""}
              onChange={(e) => setProfile((p) => ({ ...p, email: e.target.value }))}
              autoComplete="email"
            />
          </label>
          <button type="submit" className="btn btn-primary" disabled={saving}>
            {saving ? <Spinner size={14} /> : null}
            Guardar
          </button>
        </form>
      )}
    </div>
  );
}
